from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.services.gate import day_precheck, seal_day, today_str

router = APIRouter(tags=["日闸"])


class SealIn(BaseModel):
    day: str = ""
    note: str = ""


@router.get("/日闸")
def list_gates():
    from app.db import connect

    conn = connect()
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM day_gates ORDER BY day DESC").fetchall()]
        for r in rows:
            r["状态"] = "已结案" if r["sealed"] else "开放"
        return rows
    finally:
        conn.close()


@router.get("/日闸/今日")
def today_gate():
    return day_precheck(today_str())


@router.get("/日闸/预检")
def precheck(day: str = ""):
    return day_precheck(day or today_str())


@router.post("/日闸/结案")
def do_seal(body: SealIn):
    row = seal_day(body.day or None, body.note)
    row["状态"] = "已结案" if row["sealed"] else "开放"
    return row
