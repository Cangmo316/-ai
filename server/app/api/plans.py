"""
比邻AI · 康养计划路由

对应设计方案 §4.3 的 `/v1/plans/today`、`/v1/plans/checkin`，另外补齐状态机需要的
生成 / 待确认 / 确认 / 驳回 / 调整 / 汇总 / 历史。契约细节见 `uni-app/api/README.md`。

**家属确认闸门是这一层最要紧的东西**：`/v1/plans/today` 只返回已生效计划，
未确认的草稿拿不到，因此它产生不了任何提醒（提醒由调度器按 active 计划投递）。
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ..models.elder import DEFAULT_ELDER_ID, ElderStore
from ..plan.engine import PlanEngine, PlanStateError
from ..plan.models import DEFAULT_DAYS, DEFAULT_MAX_ITEMS

logger = logging.getLogger("bilin.plan.api")

router = APIRouter(prefix="/v1", tags=["plans"])


class DraftRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    elder_id: str = Field(default=DEFAULT_ELDER_ID, alias="elderId")
    goal: str = ""
    days: int = DEFAULT_DAYS
    max_items: int = Field(default=DEFAULT_MAX_ITEMS, alias="maxItems", ge=1, le=12)
    # 生成后是否直接提交家属确认（false 则停在 draft，留给将来的"编辑草稿"流程）
    submit: bool = True
    # 是否让模型把条目话术改写成更口语的说法（失败自动退回知识库原文）
    polish: bool = True
    start: str | None = None


class PlanIdRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    plan_id: str = Field(alias="planId")
    actor: str = "家属"
    reason: str = ""


class CheckinRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    plan_item_id: str = Field(alias="planItemId")
    elder_id: str = Field(default=DEFAULT_ELDER_ID, alias="elderId")
    date: str | None = None
    # done=false 表示取消打卡（老人点错了要能改）
    done: bool = True
    source: str = "elder"


def _engine(request: Request) -> PlanEngine:
    return request.app.state.plan_engine


def _elders(request: Request) -> ElderStore:
    return request.app.state.elders


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": {"code": code, "message": message}})


def _parse_day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


@router.get("/elders")
async def list_elders(request: Request):
    """老人档案列表（开发期是 3 个模拟档案，见 app/models/elder.py）"""
    elders = _elders(request).all()
    return JSONResponse(
        content={
            "elders": [
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "address": item.get("address"),
                    "age": item.get("age"),
                    "chronic": item.get("chronic") or [],
                    "careLevel": item.get("care_level") or "",
                }
                for item in elders
            ],
            "demo": True,
            "note": "开发期模拟档案，不是真实病例，也不构成医学建议",
        }
    )


@router.post("/plans/draft")
async def create_draft(payload: DraftRequest, request: Request):
    """按老人档案从知识库匹配条目 → 生成计划草稿（默认直接提交家属确认）"""
    engine = _engine(request)
    start = payload.start
    if start and _parse_day(start) is None:
        return error_response(400, "invalid_date", "日期格式不对，应该像 2026-09-24")

    try:
        plan = engine.build_plan(
            payload.elder_id,
            goal=payload.goal,
            days=payload.days,
            max_items=payload.max_items,
            start=start,
        )
        stats = {"asked": 0, "polished": 0, "fallback": 0, "reasons": ["未启用模型改写"]}
        if payload.polish:
            elder = _elders(request).get(payload.elder_id)
            provider = getattr(request.app.state, "provider", None)
            plan.items, stats = await engine.polish_items(plan.items, elder, provider)
        if payload.submit:
            engine.submit(plan)
    except PlanStateError as exc:
        return error_response(409, "plan_state", exc.message)

    return JSONResponse(
        content={
            "plan": plan.to_dict(),
            "polish": stats,
            "notice": "计划已生成，等家里人确认后才生效；未确认前不会产生任何提醒",
        }
    )


@router.get("/plans/pending")
async def pending_plans(
    request: Request,
    elder_id: str = Query(default=DEFAULT_ELDER_ID, alias="elderId"),
):
    """待家属确认的计划（家属端用；老人端不展示这个列表）"""
    plans = _engine(request).store.pending(elder_id)
    return JSONResponse(
        content={"elderId": elder_id, "plans": [plan.to_dict() for plan in plans]}
    )


@router.post("/plans/confirm")
async def confirm_plan(payload: PlanIdRequest, request: Request):
    """家属确认 → 计划生效（这一步才结束旧计划）"""
    engine = _engine(request)
    plan = engine.store.get(payload.plan_id)
    if not plan:
        return error_response(404, "plan_not_found", "没找到这份计划")
    try:
        engine.confirm(plan, actor=payload.actor or "家属")
    except PlanStateError as exc:
        return error_response(409, "plan_state", exc.message)
    logger.info("计划 %s 已由 %s 确认生效", plan.id, payload.actor)
    return JSONResponse(content={"plan": plan.to_dict(), "notice": "计划已生效，开始按时间提醒"})


@router.post("/plans/reject")
async def reject_plan(payload: PlanIdRequest, request: Request):
    engine = _engine(request)
    plan = engine.store.get(payload.plan_id)
    if not plan:
        return error_response(404, "plan_not_found", "没找到这份计划")
    try:
        engine.reject(plan, reason=payload.reason, actor=payload.actor or "家属")
    except PlanStateError as exc:
        return error_response(409, "plan_state", exc.message)
    return JSONResponse(content={"plan": plan.to_dict(), "notice": "已驳回，这份计划不会生效"})


@router.get("/plans/today")
async def today_plan(
    request: Request,
    elder_id: str = Query(default=DEFAULT_ELDER_ID, alias="elderId"),
    day: str | None = Query(default=None, alias="date"),
):
    """今日计划与打卡状态。**只返回已生效计划**——未确认的草稿产生不了提醒。"""
    target = _parse_day(day)
    if day and target is None:
        return error_response(400, "invalid_date", "日期格式不对，应该像 2026-09-24")
    return JSONResponse(content=_engine(request).today(elder_id, target))


@router.post("/plans/checkin")
async def checkin(payload: CheckinRequest, request: Request):
    """打卡 / 取消打卡（同一天同一项幂等），回流完成率"""
    engine = _engine(request)
    store = engine.store
    plan = store.active(payload.elder_id)
    if not plan:
        return error_response(409, "plan_not_active", "还没有生效的计划，先让家里人确认")

    item = next((entry for entry in plan.items if entry.id == payload.plan_item_id), None)
    if not item:
        return error_response(404, "plan_item_not_found", "没找到这一项")

    target = _parse_day(payload.date)
    if payload.date and target is None:
        return error_response(400, "invalid_date", "日期格式不对，应该像 2026-09-24")
    day_key = (target or date.today()).isoformat()

    if payload.done:
        record = store.checkin(plan, item.id, payload.elder_id, day_key, source=payload.source)
        record_payload = record.to_dict()
    else:
        store.undo_checkin(item.id, day_key)
        record_payload = None

    today = engine.today(payload.elder_id, target)
    return JSONResponse(
        content={
            "elderId": payload.elder_id,
            "date": day_key,
            "planItemId": item.id,
            "done": bool(payload.done),
            "checkin": record_payload,
            "total": today["total"],
            "completed": today["done"],
            "rate": today["rate"],
        }
    )


@router.get("/plans/summary")
async def plan_summary(
    request: Request,
    elder_id: str = Query(default=DEFAULT_ELDER_ID, alias="elderId"),
    days: int = Query(default=7, ge=1, le=30),
):
    """完成率与调整建议（家属端用）。建议只谈提醒安排，不谈治疗。"""
    engine = _engine(request)
    plan = engine.store.active(elder_id)
    if not plan:
        return JSONResponse(
            content={
                "elderId": elder_id,
                "hasPlan": False,
                "status": "",
                "stats": None,
                "suggestion": {"shouldAdjust": False, "reasons": [], "advice": "", "stats": None},
            }
        )
    return JSONResponse(
        content={
            "elderId": elder_id,
            "hasPlan": True,
            "planId": plan.id,
            "status": plan.status,
            "statusLabel": plan.status_label,
            "stats": engine.completion(plan, days=days),
            "suggestion": engine.adjustment_suggestion(plan, days=days),
        }
    )


@router.post("/plans/adjust")
async def request_adjustment(payload: PlanIdRequest, request: Request):
    """把已生效计划转入 adjusting（完成率触发的调整建议，仍需家属确认后生效）"""
    engine = _engine(request)
    plan = engine.store.get(payload.plan_id)
    if not plan:
        return error_response(404, "plan_not_found", "没找到这份计划")
    suggestion = engine.adjustment_suggestion(plan)
    reason = payload.reason or "；".join(suggestion["reasons"]) or "家属发起调整"
    try:
        engine.mark_adjusting(plan, reason)
    except PlanStateError as exc:
        return error_response(409, "plan_state", exc.message)
    return JSONResponse(
        content={"plan": plan.to_dict(), "suggestion": suggestion, "notice": "已转入调整，等家里人确认"}
    )


@router.get("/plans/history")
async def plan_history(
    request: Request,
    elder_id: str = Query(default=DEFAULT_ELDER_ID, alias="elderId"),
):
    plans = _engine(request).store.plans_of(elder_id)
    return JSONResponse(
        content={
            "elderId": elder_id,
            "plans": [
                {
                    "id": plan.id,
                    "status": plan.status,
                    "statusLabel": plan.status_label,
                    "createdAt": plan.created_at,
                    "confirmedAt": plan.confirmed_at,
                    "items": len(plan.items),
                    "knowledgeVersion": plan.knowledge_version,
                }
                for plan in plans
            ],
        }
    )
