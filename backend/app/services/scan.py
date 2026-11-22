from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException

from app.db import connect, transaction
from app.services.gate import (
    TERMINAL_STATUSES,
    ensure_day_row,
    in_flight_count,
    overdue_pending,
    refresh_in_flight,
    sealed_in,
    status_counts,
    today_str,
)


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def _ready_count(conn) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS c FROM hang_tickets WHERE status='待取'"
    ).fetchone()["c"]


def run_scan(operator: str = "系统", note: str = "", day: str | None = None) -> dict:
    """到点扫描：逾承诺日仍待取的票一律改入超期隔离并写出流水。

    这是“超期进隔离”的唯一落定入口。每张票的落定与取衣核销在同一个
    BEGIN IMMEDIATE 事务里争用：只有一方能看到 status='待取' 并写入，
    因此不可能出现“已取又隔离”。扫描与取衣的争用逐票记入扫描明细。
    """
    d = day or today_str()

    with transaction() as conn:
        ensure_day_row(conn, d)
        if sealed_in(conn, d):
            raise HTTPException(409, "当日已结案，禁止再运行超期扫描")
        counts = status_counts(conn)
        before = in_flight_count(counts)
        ready_before = counts["待取"]
        cur = conn.execute(
            """INSERT INTO overdue_scans
               (day, started_at, operator, note,
                in_flight_before, ready_before, scanned, quarantined, skipped)
               VALUES (?,?,?,?,?,?,0,0,0)""",
            (d, _now(), operator or "系统", note or "", before, ready_before),
        )
        scan_id = cur.lastrowid

    with transaction() as conn:
        candidates = overdue_pending(conn, d)

    scanned = quarantined = skipped = 0
    for cand in candidates:
        ticket_no = cand["ticket_no"]
        scanned += 1
        outcome = None
        with transaction() as conn:
            row = conn.execute(
                "SELECT * FROM hang_tickets WHERE ticket_no=?", (ticket_no,)
            ).fetchone()
            observed = row["status"] if row else "缺失"
            now = _now()
            if row is None:
                outcome = ("跳过-票不存在", observed, "")
            elif row["status"] != "待取":
                # 扫描读到它时还待取，轮到它时已被取衣（或人工处置）：记录争用结果，不改态。
                outcome = ("跳过-已非待取", observed, "扫描期间状态已被其他操作改变")
            elif not row["due_date"] or row["due_date"] >= d:
                outcome = ("跳过-未超期", observed, "承诺日不早于扫描日")
            else:
                cur = conn.execute(
                    """UPDATE hang_tickets SET status='超期隔离'
                       WHERE ticket_no=? AND status='待取'""",
                    (ticket_no,),
                )
                if cur.rowcount == 0:
                    outcome = ("跳过-争用失败", observed, "更新时已非待取")
                else:
                    conn.execute(
                        """INSERT INTO quarantines
                           (ticket_no, kind, reason, created_at, resolved,
                            source, scan_id, from_status, due_date, operator)
                           VALUES (?,?,?,?,0,'扫描',?,?,?,?)""",
                        (
                            ticket_no,
                            "超期隔离",
                            "逾承诺日未取，到点扫描进隔离",
                            now,
                            scan_id,
                            "待取",
                            row["due_date"],
                            operator or "系统",
                        ),
                    )
                    conn.execute(
                        """INSERT INTO process_events
                           (ticket_no, from_status, to_status, operator, occurred_at, note)
                           VALUES (?,?,?,?,?,?)""",
                        (
                            ticket_no,
                            "待取",
                            "超期隔离",
                            operator or "系统",
                            now,
                            "到点扫描：逾承诺日未取",
                        ),
                    )
                    outcome = ("已隔离", observed, f"承诺日 {row['due_date']}")
                    refresh_in_flight(conn)
            decision, observed_final, item_note = outcome
            conn.execute(
                """INSERT INTO scan_items
                   (scan_id, ticket_no, decision, observed_status, due_date, created_at, note)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    scan_id,
                    ticket_no,
                    decision,
                    observed_final,
                    row["due_date"] if row else cand.get("due_date", ""),
                    now,
                    item_note,
                ),
            )
        if decision == "已隔离":
            quarantined += 1
        else:
            skipped += 1

    with transaction() as conn:
        counts = status_counts(conn)
        after = in_flight_count(counts)
        conn.execute(
            """UPDATE overdue_scans
               SET finished_at=?, scanned=?, quarantined=?, skipped=?,
                   in_flight_after=?, ready_after=?
               WHERE id=?""",
            (_now(), scanned, quarantined, skipped, after, counts["待取"], scan_id),
        )
        refresh_in_flight(conn)
        scan = dict(conn.execute("SELECT * FROM overdue_scans WHERE id=?", (scan_id,)).fetchone())
        scan["items"] = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM scan_items WHERE scan_id=? ORDER BY id", (scan_id,)
            ).fetchall()
        ]
        return scan


def list_scans(limit: int = 50) -> list[dict]:
    conn = connect()
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM overdue_scans ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        ]
    finally:
        conn.close()


def get_scan(scan_id: int) -> dict:
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM overdue_scans WHERE id=?", (scan_id,)).fetchone()
        if not row:
            raise HTTPException(404, "扫描记录不存在")
        data = dict(row)
        data["items"] = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM scan_items WHERE scan_id=? ORDER BY id", (scan_id,)
            ).fetchall()
        ]
        return data
    finally:
        conn.close()


def replay_snapshot(day: str | None = None) -> dict:
    """从隔离流水与取衣记录重放挂牌终态，和现行票态互相核对。

    - 已取：有 pickups 行
    - 隔离：有 quarantines 行（取最近一条未解除的）
    - 其余：沿用现行 status

    待取可见性、在途水位均可由这套重放得出的终态重新计算，而不是另算一套。
    """
    d = day or today_str()
    conn = connect()
    try:
        tickets = {r["ticket_no"]: dict(r) for r in conn.execute("SELECT * FROM hang_tickets")}
        picked = {
            r["ticket_no"]
            for r in conn.execute("SELECT ticket_no FROM pickups").fetchall()
        }
        iso_rows: dict[str, dict] = {}
        for r in conn.execute(
            "SELECT * FROM quarantines WHERE resolved=0 ORDER BY id"
        ).fetchall():
            iso_rows[r["ticket_no"]] = dict(r)

        derived: dict[str, str] = {}
        for no, t in tickets.items():
            if no in picked:
                derived[no] = "已取"
            elif no in iso_rows:
                derived[no] = iso_rows[no]["kind"]
            else:
                derived[no] = t["status"]

        mismatches = [
            {
                "ticket_no": no,
                "现行": tickets[no]["status"],
                "重放": derived[no],
            }
            for no in sorted(tickets)
            if derived[no] != tickets[no]["status"]
        ]

        ready_derived = sum(1 for s in derived.values() if s == "待取")
        in_flight_derived = sum(1 for s in derived.values() if s not in TERMINAL_STATUSES)
        wm = conn.execute("SELECT value FROM watermarks WHERE key='在途票'").fetchone()
        stored_ready = _ready_count(conn)
        stored_in_flight = wm["value"] if wm else 0
        scan_quarantines = conn.execute(
            "SELECT COUNT(*) AS c FROM quarantines WHERE source='扫描'"
        ).fetchone()["c"]
        return {
            "day": d,
            "重放待取": ready_derived,
            "现行待取": stored_ready,
            "重放在途": in_flight_derived,
            "现行水位": stored_in_flight,
            "扫描落隔离数": scan_quarantines,
            "待取一致": ready_derived == stored_ready,
            "水位一致": in_flight_derived == stored_in_flight,
            "票态不一致": mismatches,
            "一致": not mismatches
            and ready_derived == stored_ready
            and in_flight_derived == stored_in_flight,
        }
    finally:
        conn.close()
