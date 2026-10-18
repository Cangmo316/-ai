"""
比邻AI · wiki 接口（「AI 了解我的」页面用）

为什么要有这个接口：
  wiki 是 LLM 自动学的，**它一定会学到错的东西** ——
  "我妈爱吃甜的"记错了、"老伴去世"这种敏感点记进了不合适的地方。
  如果不能看、不能改，老人会觉得"它根本不懂我，还乱记我"。

所以这里给三类操作：
  · 读：把两份 wiki 的完整内容给端侧看
  · 删：删掉某一条（记错的、不愿被记的）
  · 改：整节替换（子女一次改多条）
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ..errors import api_error
from ..models.elder import DEFAULT_ELDER_ID
from ..wiki.models import WIKI_ELDER, WIKI_PERSONA, WIKIS, WikiItem

logger = logging.getLogger("bilin.wiki")
router = APIRouter(prefix="/v1", tags=["wiki"])


class WikiItemRequest(BaseModel):
    """删一条 / 改一节。"""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    elder_id: str = Field(default="", alias="elderId")
    kind: str = Field(default=WIKI_ELDER)
    section: str = Field(default="")
    #: 删单条时用 text；整节替换时用 items
    text: str = Field(default="")
    items: list[str] = Field(default_factory=list)


def _wiki(request: Request):
    return getattr(request.app.state, "wiki", None)


def _elder_id(payload_or_query: str) -> str:
    return str(payload_or_query or "").strip() or DEFAULT_ELDER_ID


def _summary_of(request: Request, elder_id: str) -> str:
    """最近一段对话的摘要（让用户看到"它还记着哪些聊天内容"）。"""
    compactor = getattr(request.app.state, "compactor", None)
    if compactor is None:
        return ""
    summaries = getattr(compactor, "_summaries", {}) or {}
    # 会话 id 形如 ai:<accountId>，这里取最早的一条非空摘要作为代表
    for value in summaries.values():
        if value:
            return value
    return ""


@router.get("/wiki")
async def read_wiki(request: Request, elderId: str = Query(default="")):  # noqa: N803
    """读两份 wiki 的完整内容（供「AI 了解我的」页面展示）。"""
    wiki = _wiki(request)
    if wiki is None:
        return api_error("wiki_unavailable")
    elder_id = _elder_id(elderId)
    try:
        snapshot = wiki.snapshot(elder_id)
    except Exception:  # noqa: BLE001
        logger.exception("读取 wiki 失败")
        return api_error("wiki_unavailable")
    return JSONResponse(
        content={
            "elderId": elder_id,
            "elder": snapshot[WIKI_ELDER],
            "persona": snapshot[WIKI_PERSONA],
            "summary": _summary_of(request, elder_id),
        }
    )


@router.delete("/wiki/item")
async def delete_wiki_item(payload: WikiItemRequest, request: Request):
    """删掉一条记忆。

    为什么允许删：LLM 学到错的东西是必然会发生的，
    而且有些事老人**不愿被记住**（比如已经提过的伤心事）。
    能不能忘，是这套系统对老人的基本尊重。
    """
    wiki = _wiki(request)
    if wiki is None:
        return api_error("wiki_unavailable")
    kind = str(payload.kind or WIKI_ELDER).strip()
    if kind not in WIKIS:
        return api_error("wiki_kind_invalid")

    page = wiki.store.load(_elder_id(payload.elder_id), kind)
    section = page.sections.get(str(payload.section or "").strip())
    if section is None:
        return api_error("wiki_section_invalid")

    target = str(payload.text or "").strip()
    before = len(section.items)
    section.items = [item for item in section.items if item.text != target]
    if len(section.items) == before:
        return api_error("wiki_item_not_found")

    wiki.store.save(page)
    logger.info("人工删除 wiki 条目：%s / %s / %s", kind, payload.section, target[:30])
    return JSONResponse(content={"ok": True, "removed": 1})


@router.put("/wiki/section")
async def replace_wiki_section(payload: WikiItemRequest, request: Request):
    """整节替换（子女一次性改多条）。"""
    wiki = _wiki(request)
    if wiki is None:
        return api_error("wiki_unavailable")
    kind = str(payload.kind or WIKI_ELDER).strip()
    if kind not in WIKIS:
        return api_error("wiki_kind_invalid")

    page = wiki.store.load(_elder_id(payload.elder_id), kind)
    section = page.sections.get(str(payload.section or "").strip())
    if section is None:
        return api_error("wiki_section_invalid")

    cleaned: list[WikiItem] = []
    seen: set[str] = set()
    for raw in payload.items or []:
        text = str(raw or "").strip()
        if len(text) < 2 or text in seen:
            continue
        seen.add(text)
        cleaned.append(WikiItem(text=text[:60], source="manual"))

    section.items = cleaned
    wiki.store.save(page)
    logger.info("人工改写 wiki 小节：%s / %s（%d 条）", kind, payload.section, len(cleaned))
    return JSONResponse(content={"ok": True, "count": len(cleaned)})
