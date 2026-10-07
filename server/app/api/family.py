"""
比邻AI · 家人查看（绑定的家人能看到什么）

按需求：家人绑定后，点进去是**查看管理界面**——
今天的日程确认情况如何、哪些没完成、老人近期聊天活跃情况。

## 授权模型（本文件最要紧的地方）

**只有互相绑定的家人才能看**。校验走两条：
  1. `messaging.bindings_of(me)` 里有对方（绑定是双向的，见 messaging/models.py）
  2. 顺手确认对方的账号存在

不满足就 403。这条不能省：这些数据是老人的健康与行为记录，
"知道编号"绝不该等于"能看"。

## 数据来源

  · 日程：`PlanEngine.today()` / `.completion()`（与老人端同一份计划与打卡记录）
  · 聊天活跃：`MessagingStore` 里的消息（本文件自己统计，见 `_chat_activity`）
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from ..accounts import Account
from ..errors import api_error
from ..messaging import ROLE_AGENT
from .accounts import _current_account

logger = logging.getLogger("bilin.family.api")

router = APIRouter(prefix="/v1/family", tags=["family"])

#: 活跃统计看最近多少天
ACTIVITY_DAYS = 7
#: 连续活跃的判定：这天有没有消息
ACTIVE_THRESHOLD = 1


def _require_account(request: Request):
    account = _current_account(request)
    if account is None:
        return None, api_error("auth_required")
    return account, None


def _clock_date(request: Request) -> date:
    """注入时钟的"今天"（与调度器、其它路由同一个时间源）"""
    clock = request.app.state.clock
    return (clock() if callable(clock) else datetime.now()).date()


def _require_bound_peer(request: Request, number: str):
    """校验"这个编号是我的家人"。返回 (peer, None) 或 (None, 错误响应)。"""
    account, error = _require_account(request)
    if error:
        return None, None, error

    wanted = str(number or "").strip()
    if not wanted.isdigit() or len(wanted) != 8:
        return None, None, api_error("bad_request", "家人编号是 8 位数字")

    peer = request.app.state.accounts.by_number(wanted)
    if peer is None:
        return None, None, api_error("account_not_found", "没找到这个编号")

    store = request.app.state.messaging
    if store.binding_with(account.id, peer.id) is None:
        logger.warning("未绑定就查看家人数据：me=%s peer=%s", account.id, peer.id)
        return None, None, api_error("peer_not_bound")

    return account, peer, None


def _chat_activity(request: Request, peer: Account, days: int = ACTIVITY_DAYS) -> dict:
    """老人近期的聊天活跃统计。

    统计口径（都对得上老人端看到的内容）：
      · `byDay`：每天「老人自己发的」条数 + 「收到（智能体/家人）」条数
      · `total` / `activeDays` / `streak`：总量、有消息的天数、最近的连续活跃天数
      · `lastActiveAt`：老人最后一次主动发言的时间（"最近还爱不爱说话"看这个）

    **区分"老人主动"与"收到"**：只看总条数会把"家人发得多"误当成"老人活跃"。
    所以要分开算——家属真正关心的是老人自己有没有在说话。
    """
    store = request.app.state.messaging
    # 用注入的时钟取"今天"（与调度器/其他路由同一个时间源，见 main.py 的 app.state.clock）
    today = _clock_date(request)

    # 老人自己的智能体会话 + 与家人的共享会话，合起来算
    conversations = store.conversations_of(peer.id)
    buckets: dict[str, dict] = {}
    for offset in range(days - 1, -1, -1):
        key = (today - timedelta(days=offset)).isoformat()
        buckets[key] = {"date": key, "mineByHim": 0, "received": 0, "total": 0}

    last_active_at = ""
    total_mine = 0
    total_received = 0

    for conversation in conversations:
        for message in store.messages_of(conversation.id, 0):
            day = str(message.created_at or "")[:10]
            if day not in buckets:
                continue
            is_his = message.sender_id == peer.id
            # 智能体发的算"收到"，不该算成老人主动
            if is_his:
                buckets[day]["mineByHim"] += 1
                total_mine += 1
                if message.created_at > last_active_at:
                    last_active_at = message.created_at
            else:
                buckets[day]["received"] += 1
                total_received += 1
            buckets[day]["total"] += 1

    by_day = [buckets[key] for key in sorted(buckets.keys())]
    active_days = sum(1 for item in by_day if item["total"] >= ACTIVE_THRESHOLD)

    # 连续活跃：从今天往前数，连续有消息的天数
    streak = 0
    for item in reversed(by_day):
        if item["total"] >= ACTIVE_THRESHOLD:
            streak += 1
        else:
            break

    return {
        "days": days,
        "byDay": by_day,
        "totalMessages": total_mine + total_received,
        "messagesFromHim": total_mine,
        "messagesToHim": total_received,
        "activeDays": active_days,
        "streak": streak,
        "lastActiveAt": last_active_at,
    }


def _daily_trend(engine, plan, days: int, end: date) -> list[dict]:
    """最近 N 天的**逐日**完成情况，给家人的柱状图用。

    为什么不直接用 `engine.completion()`：它返回的是**聚合**数字
    （期望/完成/完成率，"最近 7 天一共做了多少"），没有逐日数组，
    所以界面上画不出"哪一天做得好、哪一天断了"——而家属看趋势正是看这个。

    口径与 `completion()` 保持一致：期望 = 当天该做的项数（每日项每天算一项），
    完成 = 当天真的打了卡的项数。
    """
    start = end - timedelta(days=max(1, days) - 1)
    records = engine.store.checkins_of(plan.elder_id, since=start.isoformat())
    done_by_date: dict[str, set[str]] = {}
    for record in records:
        if record.date > end.isoformat():
            continue
        done_by_date.setdefault(record.date, set()).add(record.plan_item_id)

    out = []
    for offset in range(max(1, days)):
        cursor = start + timedelta(days=offset)
        key = cursor.isoformat()
        due_count = 0
        for item, due, _done_today in engine.due_items(plan, cursor):
            if due:
                due_count += 1
        done_count = len(done_by_date.get(key, set()))
        out.append({
            "date": key,
            "due": due_count,
            "done": done_count,
            "rate": round(done_count / due_count, 3) if due_count else 0.0,
        })
    return out


@router.get("/overview")
async def family_overview(
    request: Request,
    number: str = Query(default=""),
    day: str | None = Query(default=None, alias="date"),
):
    """家人的查看管理界面要的全部数据：

      · `peer`      对方是谁（名字 + 编号）
      · `today`     今日日程与**每项的打卡情况**（哪些没完成一目了然）
      · `recent`    最近 7 天完成率（趋势）
      · `activity`  近期聊天活跃统计
    """
    # 只校验"是我的家人"，用不用 account 本身不重要（授权已成立）
    _account, peer, error = _require_bound_peer(request, number)
    if error:
        return error

    engine = request.app.state.plan_engine
    target = None
    if day:
        try:
            target = date.fromisoformat(day)
        except ValueError:
            return api_error("invalid_date")

    today = engine.today(peer.id, target)

    # 未完成的项：家属最关心的就是这几条
    pending = [item for item in today.get("items", []) if not item.get("done")]

    # 最近 7 天完成率（没有生效计划时给空结构，不要报错）
    recent = {}
    try:
        active = engine.store.active(peer.id)
        if active is not None:
            recent = engine.completion(active, days=7, day=target)
            # 再补一份**逐日**数据（completion() 只有聚合值，画不出趋势）
            recent = dict(recent)
            recent["byDay"] = _daily_trend(engine, active, 7, target or _clock_date(request))
    except Exception:  # noqa: BLE001
        # 完成率算不出来不该让整个管理页打不开
        logger.warning("算完成率失败（不影响今日日程）", exc_info=True)
        recent = {}

    return JSONResponse(
        content={
            "peer": {"name": peer.name, "number": peer.number, "id": peer.id},
            "today": {
                "date": today.get("date", ""),
                "statusLabel": today.get("statusLabel", ""),
                "total": today.get("total", 0),
                "done": today.get("done", 0),
                "rate": today.get("rate", 0.0),
                "items": [
                    {
                        "id": item.get("id", ""),
                        "title": item.get("title", ""),
                        "type": item.get("type", ""),
                        "time": item.get("time", ""),
                        "done": bool(item.get("done")),
                        "doneAt": item.get("doneAt", ""),
                    }
                    for item in today.get("items", [])
                ],
                "pending": [
                    {
                        "id": item.get("id", ""),
                        "title": item.get("title", ""),
                        "time": item.get("time", ""),
                    }
                    for item in pending
                ],
                "pendingCount": len(pending),
            },
            "recent": recent,
            "activity": _chat_activity(request, peer),
        }
    )
