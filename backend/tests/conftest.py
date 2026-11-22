import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="hangslip-test-"))
os.environ["HANGSLIP_DB"] = str(_TMP / "test.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import connect, init_db  # noqa: E402
from app.main import app  # noqa: E402

TABLES = (
    "scan_items",
    "overdue_scans",
    "quarantines",
    "process_events",
    "pickups",
    "ticket_items",
    "hang_tickets",
    "day_gates",
    "watermarks",
    "stores",
    "settings",
)


@pytest.fixture()
def client():
    init_db()
    conn = connect()
    try:
        for t in TABLES:
            conn.execute(f"DELETE FROM {t}")
        conn.execute(
            "INSERT INTO stores(code, name, rack_count, active) VALUES ('店-测','测试店',2,1)"
        )
        conn.commit()
    finally:
        conn.close()
    with TestClient(app) as c:
        yield c


def add_ticket(
    client,
    ticket_no: str,
    status: str = "待取",
    due_date: str = "2020-01-01",
    pickup_code: str = "码",
) -> None:
    from app.db import transaction
    from app.services.gate import refresh_in_flight

    with transaction() as conn:
        conn.execute(
            """INSERT INTO hang_tickets
               (ticket_no, store_code, pickup_code, customer_name, status,
                opened_at, due_date, note)
               VALUES (?,?,?,?,?,?,?, '')""",
            (ticket_no, "店-测", pickup_code, "顾客", status, "2020-01-01 09:00:00", due_date),
        )
        refresh_in_flight(conn)
