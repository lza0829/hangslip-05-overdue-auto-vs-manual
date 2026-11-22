"""超期进隔离：以到点扫描为唯一权威的口径验收。

约定（全局唯一一套）：
1. 逾承诺日仍待取的票，只有到点扫描能把它改入超期隔离；
2. 每次扫描写出隔离流水（source='扫描'）与逐票扫描明细；
3. 待取可见性 / 总览超期数 / 在途水位都必须能由隔离与取衣结果重放出同一答案；
4. 扫描改态与取衣核销争用同一把锁，绝不允许「已取又隔离」；
5. 日闸预检在超期票未落隔离、或今日未扫描时阻止结案。
"""

from conftest import add_ticket, connect
from app.services.scan import replay_snapshot


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


def test_scan_moves_overdue_ready_ticket_into_quarantine_with_log(client):
    add_ticket(client, "T-1", status="待取", due_date="2020-01-01")
    add_ticket(client, "T-2", status="待取", due_date="2999-01-01")  # 未超期
    add_ticket(client, "T-3", status="水洗", due_date="2020-01-01")  # 非待取

    result = scan(client)

    assert result["scanned"] == 1
    assert result["quarantined"] == 1
    assert status_of("T-1") == "超期隔离"
    assert status_of("T-2") == "待取"
    assert status_of("T-3") == "水洗"

    logs = client.get("/api/隔离").json()
    assert len(logs) == 1
    log = logs[0]
    assert log["ticket_no"] == "T-1"
    assert log["kind"] == "超期隔离"
    assert log["source"] == "扫描"
    assert log["scan_id"] == result["id"]
    assert log["from_status"] == "待取"
    assert log["due_date"] == "2020-01-01"

    detail = client.get(f"/api/超期扫描/{result['id']}").json()
    assert [i["ticket_no"] for i in detail["items"]] == ["T-1"]
    assert detail["items"][0]["decision"] == "已隔离"


def test_ready_page_no_longer_shows_scanned_ticket(client):
    add_ticket(client, "T-1", status="待取", due_date="2020-01-01")
    add_ticket(client, "T-2", status="待取", due_date="2999-01-01")

    assert {t["ticket_no"] for t in client.get("/api/挂牌?status=待取").json()} == {"T-1", "T-2"}
    scan(client)
    ready = client.get("/api/挂牌?status=待取").json()
    assert {t["ticket_no"] for t in ready} == {"T-2"}

    dash = client.get("/api/总览").json()
    assert dash["待取"] == 1
    assert dash["超期隔离"] == 1
    assert dash["超期待取数"] == 0
    assert dash["今日扫描已跑"] is True


def test_dashboard_overdue_count_drops_to_zero_only_after_scan(client):
    add_ticket(client, "T-1", status="待取", due_date="2020-01-01")
    add_ticket(client, "T-2", status="待取", due_date="2020-01-02")
    assert client.get("/api/总览").json()["超期待取数"] == 2
    scan(client)
    assert client.get("/api/总览").json()["超期待取数"] == 0
    assert client.get("/api/超期扫描/待扫").json() == []


def test_scan_writes_no_log_for_non_overdue(client):
    add_ticket(client, "T-1", status="待取", due_date="2999-01-01")
    result = scan(client)
    assert result["scanned"] == 0
    assert result["quarantined"] == 0
    assert client.get("/api/隔离").json() == []


def test_manual_overdue_quarantine_is_forbidden(client):
    add_ticket(client, "T-1", status="待取", due_date="2020-01-01")
    r = client.post(
        "/api/挂牌/T-1/隔离", json={"kind": "超期隔离", "reason": "手工"}
    )
    assert r.status_code == 409
    assert status_of("T-1") == "待取"
    assert client.get("/api/隔离").json() == []


def test_manual_lost_quarantine_still_allowed_and_logged(client):
    add_ticket(client, "T-1", status="待取", due_date="2999-01-01")
    r = client.post("/api/挂牌/T-1/隔离", json={"kind": "丢失隔离", "reason": "店内申报"})
    assert r.status_code == 200, r.text
    assert status_of("T-1") == "丢失隔离"
    logs = client.get("/api/隔离").json()
    assert len(logs) == 1
    assert logs[0]["source"] == "人工"
    assert logs[0]["scan_id"] is None


def test_pickup_after_scan_is_rejected_no_double_state(client):
    add_ticket(client, "T-1", status="待取", due_date="2020-01-01", pickup_code="暗67")
    scan(client)
    r = client.post("/api/挂牌/T-1/取衣", json={"pickup_code": "暗67"})
    assert r.status_code == 409
    assert status_of("T-1") == "超期隔离"


def test_pickup_before_scan_wins_and_scan_records_race(client):
    # 取衣先发生：扫描前已取，扫描的候选集为空，不应再隔离。
    add_ticket(client, "T-1", status="待取", due_date="2020-01-01", pickup_code="暗67")
    r = client.post("/api/挂牌/T-1/取衣", json={"pickup_code": "暗67"})
    assert r.status_code == 200
    result = scan(client)
    assert result["scanned"] == 0
    assert status_of("T-1") == "已取"
    assert client.get("/api/隔离").json() == []


def test_scan_twice_is_idempotent(client):
    add_ticket(client, "T-1", status="待取", due_date="2020-01-01")
    first = scan(client)
    second = scan(client)
    assert first["quarantined"] == 1
    assert second["scanned"] == 0
    assert second["quarantined"] == 0
    assert len(client.get("/api/隔离").json()) == 1


def test_gate_precheck_blocks_until_scan_then_allows(client):
    add_ticket(client, "T-1", status="待取", due_date="2020-01-01")

    pre = client.get("/api/日闸/预检").json()
    assert pre["可结案"] is False
    assert pre["超期待扫数"] == 1
    assert any("扫描" in b for b in pre["阻塞原因"])

    r = client.post("/api/日闸/结案", json={"note": "x"})
    assert r.status_code == 409

    scan(client)
    pre = client.get("/api/日闸/预检").json()
    assert pre["可结案"] is True, pre
    r = client.post("/api/日闸/结案", json={"note": "x"})
    assert r.status_code == 200
    assert r.json()["sealed"] == 1


def test_gate_requires_scan_even_with_no_overdue(client):
    add_ticket(client, "T-1", status="待取", due_date="2999-01-01")
    pre = client.get("/api/日闸/预检").json()
    assert pre["可结案"] is False
    assert any("尚未运行" in b for b in pre["阻塞原因"])
    scan(client)
    assert client.get("/api/日闸/预检").json()["可结案"] is True


def test_replay_matches_current_state_and_watermark(client):
    add_ticket(client, "T-1", status="待取", due_date="2020-01-01")
    add_ticket(client, "T-2", status="待取", due_date="2999-01-01", pickup_code="码2")
    add_ticket(client, "T-3", status="水洗", due_date="2999-01-01")
    scan(client)
    client.post("/api/挂牌/T-2/取衣", json={"pickup_code": "码2"})

    snap = client.get("/api/超期扫描/核对").json()
    assert snap["一致"] is True, snap
    assert snap["票态不一致"] == []
    assert snap["扫描落隔离数"] == 1
    assert snap["现行待取"] == 0
    assert snap["现行水位"] == 2  # T-1 超期隔离、T-3 水洗仍在途


def test_watermark_recomputed_and_consistent_after_scan(client):
    add_ticket(client, "T-1", status="待取", due_date="2020-01-01")
    add_ticket(client, "T-2", status="待取", due_date="2020-01-01")
    assert client.get("/api/总览").json()["在途水位"] == 2
    scans = scan(client)
    # 超期隔离仍算在途（衣仍在店内待处置），水位不因扫描而虚减；
    # 但待取数必须归零，且水位与重放口径一致。
    assert scans["in_flight_before"] == 2
    assert scans["in_flight_after"] == 2
    assert scans["ready_before"] == 2
    assert scans["ready_after"] == 0
    dash = client.get("/api/总览").json()
    assert dash["在途水位"] == 2
    assert dash["待取"] == 0
    assert dash["超期隔离"] == 2
    assert client.get("/api/超期扫描/核对").json()["一致"] is True


def test_scan_blocked_after_day_sealed(client):
    add_ticket(client, "T-1", status="待取", due_date="2999-01-01")
    scan(client)
    client.post("/api/日闸/结案", json={"note": "x"})
    r = client.post("/api/超期扫描", json={"operator": "巡检"})
    assert r.status_code == 409


def test_replay_detects_out_of_band_state_change(client):
    add_ticket(client, "T-1", status="待取", due_date="2020-01-01")
    scan(client)
    conn = connect()
    try:
        conn.execute("UPDATE hang_tickets SET status='待取' WHERE ticket_no='T-1'")
        conn.commit()
    finally:
        conn.close()
    snap = client.get("/api/超期扫描/核对").json()
    assert snap["一致"] is False
    assert snap["票态不一致"][0]["ticket_no"] == "T-1"
