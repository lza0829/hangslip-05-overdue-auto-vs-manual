"""扫描改态与取衣核销的争用必须可核：两者共用 BEGIN IMMEDIATE，谁先看到「待取」谁落定。"""

import threading

from conftest import add_ticket, connect
from app.services import scan as scan_svc


def scan(client, **kw):
    r = client.post("/api/超期扫描", json={"operator": "巡检", **kw})
    assert r.status_code == 200, r.text
    return r.json()


def status_of(ticket_no):
    conn = connect()
    try:
        return conn.execute(
            "SELECT status FROM hang_tickets WHERE ticket_no=?", (ticket_no,)
        ).fetchone()["status"]
    finally:
        conn.close()


def rows(sql, args=()):
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def test_stale_candidate_picked_up_mid_scan_is_recorded_not_quarantined(client, monkeypatch):
    """扫描已读到「待取」，轮到该票前取衣先落定：扫描记跳过、绝不改态。"""
    add_ticket(client, "T-1", status="待取", due_date="2020-01-01", pickup_code="暗67")
    stale = rows("SELECT * FROM hang_tickets WHERE ticket_no='T-1'")
    r = client.post("/api/挂牌/T-1/取衣", json={"pickup_code": "暗67"})
    assert r.status_code == 200

    monkeypatch.setattr(scan_svc, "overdue_pending", lambda conn, day=None: stale)
    result = scan_svc.run_scan("巡检")

    assert result["scanned"] == 1
    assert result["quarantined"] == 0
    assert result["skipped"] == 1
    assert result["items"][0]["decision"] == "跳过-已非待取"
    assert status_of("T-1") == "已取"
    assert rows("SELECT * FROM quarantines") == []
    assert len(rows("SELECT * FROM pickups")) == 1


def test_scan_and_pickup_race_never_yields_pickup_plus_quarantine(client):
    """并发跑扫描与取衣：终态只能是其中一种，且落定方必有对应记录。"""
    rounds = 8
    for i in range(rounds):
        no = f"R-{i}"
        add_ticket(client, no, status="待取", due_date="2020-01-01", pickup_code=f"码{i}")

    errors: list[str] = []

    def worker_pick(no, code):
        try:
            r = client.post(f"/api/挂牌/{no}/取衣", json={"pickup_code": code})
            if r.status_code not in (200, 403, 409):
                errors.append(f"pick {no}: {r.status_code} {r.text}")
        except Exception as e:  # pragma: no cover
            errors.append(f"pick {no}: {e}")

    for i in range(rounds):
        no = f"R-{i}"
        t1 = threading.Thread(target=worker_pick, args=(no, f"码{i}"))
        t2 = threading.Thread(target=lambda: client.post("/api/超期扫描", json={"operator": "巡检"}))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

    # 扫描清空所有超期待取票，确保本轮全部落定
    scan(client)

    assert errors == []
    for i in range(rounds):
        no = f"R-{i}"
        st = status_of(no)
        n_q = len(rows("SELECT * FROM quarantines WHERE ticket_no=?", (no,)))
        n_p = len(rows("SELECT * FROM pickups WHERE ticket_no=?", (no,)))
        assert st in ("已取", "超期隔离"), (no, st)
        if st == "已取":
            assert n_p == 1 and n_q == 0, (no, st, n_p, n_q)
        else:
            assert n_q == 1 and n_p == 0, (no, st, n_p, n_q)

    snap = client.get("/api/超期扫描/核对").json()
    assert snap["一致"] is True, snap
