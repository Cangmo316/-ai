"""
比邻AI · 主动关心接口

「关心」在端侧需要能看到的只有两件事：
  · 今天问了几次、问了什么（频率控制是否正常）
  · 有哪些约好的事快到日子了（回访清单）

主动提问本身由后台循环发出（app/care/loop.py），
会以 AI 消息的形式出现在会话里，所以这个接口**只读**。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from ..errors import api_error
from ..models.elder import DEFAULT_ELDER_ID

logger = logging.getLogger("bilin.care")
router = APIRouter(prefix="/v1", tags=["care"])


@router.get("/care")
async def read_care(request: Request, elderId: str = Query(default="")):  # noqa: N803
    """看今天的主动关心情况与到期的回访。"""
    care = getattr(request.app.state, "care", None)
    if care is None:
        return api_error("care_unavailable")
    elder_id = str(elderId or "").strip() or DEFAULT_ELDER_ID
    try:
        data = care.snapshot(elder_id)
    except Exception:  # noqa: BLE001
        logger.exception("读取关心状态失败")
        return api_error("care_unavailable")
    return JSONResponse(content={"elderId": elder_id, **data})


@router.post("/care/ask")
async def trigger_ask(request: Request, elderId: str = Query(default="")):  # noqa: N803
    """手动触发一次主动关心（联调/演示用）。

    正式流程靠后台循环；这个接口用来在演示时立刻看到效果，
    也方便验证"频率控制有没有生效"（被拒时会返回原因）。
    """
    care = getattr(request.app.state, "care", None)
    if care is None:
        return api_error("care_unavailable")
    elder_id = str(elderId or "").strip() or DEFAULT_ELDER_ID

    ok, reason = care.should_ask(elder_id)
    if not ok:
        # 不当作错误：这是正常的频率控制结果，如实告诉调用方原因
        return JSONResponse(content={"asked": False, "reason": reason})

    # 与后台循环一致：先预览，投递成功才记账
    ask = care.preview_ask(elder_id)
    if ask is None:
        return JSONResponse(content={"asked": False, "reason": "被频率控制拦下"})

    delivered = False
    loop = getattr(request.app.state, "care_loop", None)
    if loop is not None:
        delivered = loop._deliver(elder_id, ask)
    else:
        try:
            from ..care.loop import CareLoop

            CareLoop(care, request.app.state.chat_service.store, elder_ids=[])._deliver(
                elder_id, ask
            )
            delivered = True
        except Exception:  # noqa: BLE001
            logger.exception("手动触发关心时投递失败")

    if not delivered:
        # 没投出去就不记账 —— 否则这条没送到的提问会占掉当天的名额
        return JSONResponse(
            content={"asked": False, "delivered": False, "reason": "还没有会话可以投递"}
        )

    care.commit_ask(ask)
    return JSONResponse(content={"asked": True, "delivered": True, "ask": ask.to_dict()})
