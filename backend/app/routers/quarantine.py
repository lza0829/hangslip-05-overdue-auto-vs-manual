from __future__ import annotations

from fastapi import APIRouter, Query

from app.db import connect

router = APIRouter(tags=["隔离"])


@router.get("/隔离")
def list_quarantine(ticket_no: str | None = Query(None)):
    """现行隔离流水：人工丢失隔离与到点扫描超期隔离共用一张表，字段区分来源。"""
    conn = connect()
    try:
        sql = "SELECT * FROM quarantines WHERE 1=1"
        args: list = []
        if ticket_no:
            sql += " AND ticket_no=?"
            args.append(ticket_no)
        sql += " ORDER BY id DESC"
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()
