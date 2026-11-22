from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.db import connect
from app.services import scan as svc
from app.services.gate import overdue_pending, public_ticket

router = APIRouter(tags=["超期扫描"])


class ScanIn(BaseModel):
    operator: str = "系统"
    note: str = ""
    day: str = ""


@router.get("/超期扫描/待扫")
def pending():
    conn = connect()
    try:
        return [public_ticket(t) for t in overdue_pending(conn)]
    finally:
        conn.close()


@router.get("/超期扫描")
def list_scans():
    return svc.list_scans()


@router.get("/超期扫描/核对")
def replay():
    return svc.replay_snapshot()


@router.get("/超期扫描/{scan_id}")
def get_scan(scan_id: int):
    return svc.get_scan(scan_id)


@router.post("/超期扫描")
def run_scan(body: ScanIn):
    return svc.run_scan(body.operator, body.note, body.day or None)
