from __future__ import annotations

from datetime import date, datetime

from fastapi import HTTPException

from app.db import connect, transaction

TERMINAL_STATUSES = ("已取", "丢失隔离")


def today_str() -> str:
    return date.today().isoformat()


def is_day_sealed(day: str | None = None) -> bool:
    d = day or today_str()
    conn = connect()
    try:
        return sealed_in(conn, d)
    finally:
        conn.close()


def sealed_in(conn, day: str) -> bool:
    """事务内判结案：与结案动作共用 BEGIN IMMEDIATE，避免“预检通过后又被写入”。"""
    row = conn.execute("SELECT sealed FROM day_gates WHERE day=?", (day,)).fetchone()
    return bool(row and row["sealed"])


def ensure_day_row(conn, day: str | None = None) -> str:
    d = day or today_str()
    row = conn.execute("SELECT day FROM day_gates WHERE day=?", (d,)).fetchone()
    if not row:
        conn.execute(
            "INSERT INTO day_gates(day, sealed, sealed_at, note) VALUES (?,?,?,?)",
            (d, 0, None, ""),
        )
    return d


def status_counts(conn) -> dict[str, int]:
    counts = {
        "已收": 0,
        "水洗": 0,
        "烘干": 0,
        "熨烫": 0,
        "待取": 0,
        "已取": 0,
        "超期隔离": 0,
        "丢失隔离": 0,
    }
    for row in conn.execute(
        "SELECT status, COUNT(*) AS c FROM hang_tickets GROUP BY status"
    ).fetchall():
        counts[row["status"]] = row["c"]
    return counts


def overdue_pending(conn, day: str | None = None) -> list[dict]:
    """逾承诺日、仍挂待取的票。超期进隔离的唯一入口是到点扫描。"""
    d = day or today_str()
    return [
        dict(r)
        for r in conn.execute(
            """SELECT * FROM hang_tickets
               WHERE status='待取' AND due_date <> '' AND due_date < ?
               ORDER BY due_date, id""",
            (d,),
        ).fetchall()
    ]


def in_flight_count(counts: dict[str, int]) -> int:
    return sum(c for s, c in counts.items() if s not in TERMINAL_STATUSES)


def refresh_in_flight(conn) -> int:
    """水位只由挂牌终态推导；隔离落定与取衣核销在同一事务里刷新。"""
    n = in_flight_count(status_counts(conn))
    now = datetime.now().replace(microsecond=0).isoformat(sep=" ")
    conn.execute(
        """INSERT INTO watermarks(key, value, updated_at) VALUES ('在途票', ?, ?)
           ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
        (n, now),
    )
    return n


def today_scan(conn, day: str | None = None) -> dict | None:
    """当日最近一次扫描：优先已完成的，避免中途崩溃的残行永久卡住预检。"""
    d = day or today_str()
    row = conn.execute(
        """SELECT * FROM overdue_scans
           WHERE day=? AND finished_at IS NOT NULL
           ORDER BY id DESC LIMIT 1""",
        (d,),
    ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT * FROM overdue_scans WHERE day=? ORDER BY id DESC LIMIT 1", (d,)
        ).fetchone()
    return dict(row) if row else None


def public_ticket(row: dict) -> dict:
    """对外暴露的待扫票面：隐去取衣暗码。"""
    return {k: v for k, v in row.items() if k != "pickup_code"}


def day_precheck(day: str | None = None) -> dict:
    """日闸预检：结案前必须让超期待取票先经扫描落隔离。"""
    d = day or today_str()
    conn = connect()
    try:
        gate = conn.execute("SELECT * FROM day_gates WHERE day=?", (d,)).fetchone()
        pending = overdue_pending(conn, d)
        scan = today_scan(conn, d)
        ready = conn.execute(
            "SELECT COUNT(*) AS c FROM hang_tickets WHERE status='待取'"
        ).fetchone()["c"]
        qrows = conn.execute(
            "SELECT COUNT(*) AS c FROM quarantines WHERE substr(created_at,1,10)=?",
            (d,),
        ).fetchone()["c"]
        blocked: list[str] = []
        if pending:
            blocked.append(f"尚有 {len(pending)} 张逾承诺日待取票未进隔离，请先运行到点扫描")
        if scan is None:
            blocked.append("今日尚未运行超期扫描")
        elif scan["finished_at"] is None:
            blocked.append("今日超期扫描未完成")
        sealed = bool(gate and gate["sealed"])
        return {
            "day": d,
            "sealed": sealed,
            "状态": "已结案" if sealed else "开放",
            "sealed_at": gate["sealed_at"] if gate else None,
            "待取数": ready,
            "超期待扫数": len(pending),
            "超期待扫": [public_ticket(t) for t in pending],
            "今日扫描": scan,
            "今日隔离流水数": qrows,
            "可结案": not blocked,
            "阻塞原因": blocked,
        }
    finally:
        conn.close()


def seal_day(day: str | None = None, note: str = "") -> dict:
    d = day or today_str()
    with transaction() as conn:
        ensure_day_row(conn, d)
        if sealed_in(conn, d):
            return dict(conn.execute("SELECT * FROM day_gates WHERE day=?", (d,)).fetchone())
        pending = overdue_pending(conn, d)
        if pending:
            raise HTTPException(
                409,
                f"日闸预检未过：{len(pending)} 张逾承诺日待取票未进隔离，请先运行超期扫描",
            )
        scan = today_scan(conn, d)
        if scan is None or scan["finished_at"] is None:
            raise HTTPException(409, "日闸预检未过：今日超期扫描尚未完成")
        now = datetime.now().replace(microsecond=0).isoformat(sep=" ")
        conn.execute(
            "UPDATE day_gates SET sealed=1, sealed_at=?, note=? WHERE day=?",
            (now, note, d),
        )
        return dict(conn.execute("SELECT * FROM day_gates WHERE day=?", (d,)).fetchone())
