"""
比邻AI · 提醒与调度路由

老人端只用两个：`GET /v1/reminders/inbox`（拉要展示的提醒）+ `POST /v1/reminders/read`（回执已看到）。
其余是家属端/运营端的可追溯查询，以及联调用的手动 tick。
"""

from __future__ import annotations

import logging
from datetime import date, datetime

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from ..errors import api_error
from pydantic import BaseModel, ConfigDict, Field

from ..models.elder import DEFAULT_ELDER_ID

logger = logging.getLogger("bilin.schedule.api")

router = APIRouter(prefix="/v1", tags=["reminders"])


class ReadRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    elder_id: str = Field(default=DEFAULT_ELDER_ID, alias="elderId")
    task_id: str | None = Field(default=None, alias="taskId")


class TickRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    # 手动把时间推到某一刻（联调/演示用）。不传=用当前真实时间
    at: str | None = None


def _scheduler(request: Request):
    return request.app.state.scheduler


def _today(request: Request):
    """统一时间源（见 main.py 的 app.state.clock）"""
    scheduler = _scheduler(request)
    return scheduler.now().date()


def _parse_moment(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@router.get("/reminders/inbox")
async def reminder_inbox(
    request: Request,
    elder_id: str = Query(default=DEFAULT_ELDER_ID, alias="elderId"),
):
    """老人端要展示的提醒（已投递、还没被看到过）"""
    scheduler = _scheduler(request)
    tasks = scheduler.reminders.inbox(elder_id)
    return JSONResponse(
        content={
            "elderId": elder_id,
            "tasks": [task.to_dict() for task in tasks],
            "count": len(tasks),
        }
    )


@router.post("/reminders/read")
async def mark_read(payload: ReadRequest, request: Request):
    """收到即回执（老人看到了）。不传 taskId 表示整个收件箱都看过了。"""
    scheduler = _scheduler(request)
    count = scheduler.reminders.mark_read(payload.elder_id, payload.task_id, scheduler.now())
    return JSONResponse(content={"elderId": payload.elder_id, "marked": count})


@router.get("/reminders/tasks")
async def reminder_tasks(
    request: Request,
    elder_id: str = Query(default=DEFAULT_ELDER_ID, alias="elderId"),
    day: str | None = Query(default=None, alias="date"),
):
    """提醒任务与状态（可追溯：发没发、什么时候发的、老人打没打卡）"""
    scheduler = _scheduler(request)
    target = day or _today(request).isoformat()
    if _parse_moment(target) is None:
        return api_error("invalid_date")
    tasks = scheduler.reminders.tasks_of(elder_id, target)
    return JSONResponse(
        content={
            "elderId": elder_id,
            "date": target,
            "tasks": [task.to_dict() for task in tasks],
        }
    )


@router.get("/scheduler/status")
async def scheduler_status(request: Request):
    """调度器自检：跑了多少轮、有哪些通道、各状态任务数、下一条提醒什么时候发"""
    return JSONResponse(content=_scheduler(request).status())


@router.post("/scheduler/tick")
async def scheduler_tick(payload: TickRequest, request: Request):
    """手动推进一次调度（联调/演示用）。

    生产环境应把 `SCHEDULER_MANUAL_TICK` 关掉——否则任何人都能触发提醒投递。
    """
    scheduler = _scheduler(request)
    if not scheduler.settings.scheduler_manual_tick:
        return api_error("manual_tick_disabled")
    moment = None
    if payload.at:
        moment = _parse_moment(payload.at)
        if moment is None:
            return api_error("invalid_datetime")
    summary = await scheduler.tick(moment)
    return JSONResponse(content={"summary": summary, "status": scheduler.status()})
