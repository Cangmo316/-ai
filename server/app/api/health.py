"""
比邻AI · 健康档案路由

老人端/家人端用这几个：

    GET    /v1/health/types              有哪些测量项、各项要填什么（端侧不用写死）
    GET    /v1/health/records            我的记录（可按项筛）
    POST   /v1/health/records            记一条
    DELETE /v1/health/records/{id}       删一条（填错了）

鉴权：`Authorization: Bearer <token>`。记录归属当前账号
（`elder_id` 就是账号 id），**不能替别人记**——否则谁都能往别人档案里写数。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ..errors import api_error
from ..health import HEALTH_ITEM_TYPES, SOURCE_DEVICE, SOURCE_MANUAL, validate_values, summarize
from .accounts import _current_account

logger = logging.getLogger("bilin.health.api")

router = APIRouter(prefix="/v1/health", tags=["health"])

#: 一次最多返回多少条
MAX_LIMIT = 500


class RecordRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    item_type: str = Field(default="", alias="itemType")
    values: dict = Field(default_factory=dict)
    measured_at: str = Field(default="", alias="measuredAt")
    note: str = Field(default="")
    source: str = Field(default=SOURCE_MANUAL)


def _store(request: Request):
    return request.app.state.health


def _require_account(request: Request):
    account = _current_account(request)
    if account is None:
        return None, api_error("auth_required")
    return account, None


def _types_payload() -> list[dict]:
    """测量项定义下发（端侧据此渲染表单，不用把字段写死在页面里）"""
    out = []
    for key, spec in HEALTH_ITEM_TYPES.items():
        out.append({
            "itemType": key,
            "label": spec["label"],
            "unit": spec.get("unit", ""),
            "fields": spec["fields"],
            "timings": spec.get("timings", []),
            "normalRange": spec.get("normalRange", ""),
            "hint": spec.get("hint", ""),
        })
    return out


@router.get("/types")
async def health_types():
    """测量项定义。**不要求登录**：填表前先渲染表单，这时可能还没登录态。"""
    return JSONResponse(content={"types": _types_payload()})


@router.get("/records")
async def list_records(
    request: Request,
    item_type: str = Query(default="", alias="itemType"),
    limit: int = Query(default=100, alias="limit"),
):
    """我的健康记录（按测量时间倒序）"""
    account, error = _require_account(request)
    if error:
        return error

    capped = max(1, min(int(limit or 100), MAX_LIMIT))
    records = _store(request).records_of(account.id, item_type=item_type, limit=capped)
    return JSONResponse(
        content={
            "records": [record.to_dict() for record in records],
            "count": len(records),
        }
    )


@router.post("/records")
async def add_record(payload: RecordRequest, request: Request):
    """记一条测量数据。

    校验在 `validate_values` 里（服务端是唯一事实来源，端侧的即时校验只是提前反馈）。
    """
    account, error = _require_account(request)
    if error:
        return error

    item_type = str(payload.item_type or "").strip()
    if not item_type:
        return api_error("bad_request", "没说是什么测量项")

    values, problem = validate_values(item_type, payload.values or {})
    if problem:
        return api_error("health_value_invalid", problem)

    source = payload.source if payload.source in (SOURCE_MANUAL, SOURCE_DEVICE) else SOURCE_MANUAL
    record = _store(request).add(
        elder_id=account.id,
        item_type=item_type,
        values=values,
        measured_at=str(payload.measured_at or "").strip(),
        note=str(payload.note or "").strip()[:100],
        source=source,
    )
    logger.info(
        "健康记录：%s %s %s",
        account.name,
        record.item_type,
        summarize(record.item_type, record.values),
    )
    return JSONResponse(content={"record": record.to_dict()}, status_code=201)


@router.delete("/records/{record_id}")
async def delete_record(record_id: str, request: Request):
    """删一条（填错了）。**只能删自己的**。"""
    account, error = _require_account(request)
    if error:
        return error

    store = _store(request)
    record = store.find(record_id)
    if record is None:
        return api_error("not_found", "没找到这条记录")
    if record.elder_id != account.id:
        logger.warning("越权删健康记录：me=%s owner=%s", account.id, record.elder_id)
        return api_error("forbidden")

    store.remove(record_id)
    return JSONResponse(content={"ok": True})


@router.get("/summary")
async def health_summary(request: Request):
    """我的健康数据概览：每项最近一条 + 条数。

    端侧「健康档案」页的顶部卡片用它，也方便家属端将来复用同一份口径。
    """
    account, error = _require_account(request)
    if error:
        return error

    store = _store(request)
    items = []
    for key, spec in HEALTH_ITEM_TYPES.items():
        latest = store.latest_of(account.id, key)
        all_of_type = store.records_of(account.id, item_type=key)
        items.append({
            "itemType": key,
            "label": spec["label"],
            "unit": spec.get("unit", ""),
            "normalRange": spec.get("normalRange", ""),
            "count": len(all_of_type),
            "latest": latest.to_dict() if latest else None,
        })
    return JSONResponse(content={"items": items})
