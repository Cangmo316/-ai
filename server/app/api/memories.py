"""
比邻AI · 记忆接口（L2 经历 / L3 偏好）

给两类调用方用：
- **家人端**：录入（"我妈 2023 年去过海南"）、复核自动整理的条目、单条删除、一键清空
- **老人端**：暂时只读（看"智能体记得我什么"），写入由对话自动整理或家人端完成

⚠️ 两条隐私口径写死在代码里，不靠调用方自觉（见设计方案 §3.4）：
1. `scope=family` 时**只返回 `visibleToFamily=True` 的**：从聊天自动整理出来的记忆默认
   家属看不到——否则"家人端默认看不到聊天原文"会被记忆绕过去
2. 待复核（`review=pending`）的条目**默认不出现在列表里**（`includePending=true` 才给），
   它们也不参与检索与主动话题
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ..errors import api_error
from ..memory import KINDS, MemoryStore
from ..memory.retrieval import search, topics
from ..models.elder import DEFAULT_ELDER_ID

router = APIRouter(prefix="/v1", tags=["memories"])


class MemoryCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    text: str
    elder_id: str = Field(default=DEFAULT_ELDER_ID, alias="elderId")
    kind: str = "experience"
    tags: list[str] = Field(default_factory=list)
    source: str = "family"
    happened_at: str = Field(default="", alias="happenedAt")
    visible_to_family: bool | None = Field(default=None, alias="visibleToFamily")


class MemoryUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    text: str | None = None
    kind: str | None = None
    tags: list[str] | None = None
    happened_at: str | None = Field(default=None, alias="happenedAt")
    visible_to_family: bool | None = Field(default=None, alias="visibleToFamily")


class MemoryReview(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str
    approve: bool = True


class MemorySettingsUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    elder_id: str = Field(default=DEFAULT_ELDER_ID, alias="elderId")
    auto_extract: bool | None = Field(default=None, alias="autoExtract")


class ClearRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    elder_id: str = Field(default=DEFAULT_ELDER_ID, alias="elderId")


def _store(request: Request) -> MemoryStore:
    return request.app.state.memories


@router.get("/memories")
async def list_memories(
    request: Request,
    elder_id: str = Query(default=DEFAULT_ELDER_ID, alias="elderId"),
    kind: str | None = Query(default=None),
    q: str | None = Query(default=None, description="按相关性检索（不填就按时间倒序全列）"),
    include_pending: bool = Query(default=False, alias="includePending"),
    scope: str = Query(default="family", description="family=只给家属可见的；all=全部（老人端）"),
    limit: int = Query(default=50, ge=1, le=200),
):
    store = _store(request)
    if kind is not None and kind not in KINDS:
        return api_error("invalid_request", "记忆种类不合法")

    if q:
        # 检索路径只走"已复核可用"的记忆（families/pending 的天然被排除）
        ranked = search(store, elder_id, q, limit=limit)
        return JSONResponse(
            content={
                "elderId": elder_id,
                "query": q,
                "scope": scope,
                "count": len(ranked),
                "memories": [
                    dict(entry.to_dict(), score=round(value, 3)) for entry, value in ranked
                ],
            }
        )

    entries = store.all_of(elder_id) if scope == "all" else store.family_view(elder_id)
    if kind is not None:
        entries = [entry for entry in entries if entry.kind == kind]
    if not include_pending:
        entries = [entry for entry in entries if entry.review != "pending"]
    entries = entries[:limit]
    return JSONResponse(
        content={
            "elderId": elder_id,
            "scope": scope,
            "count": len(entries),
            "memories": [entry.to_dict() for entry in entries],
            "pendingCount": len(store.pending_of(elder_id)),
        }
    )


@router.post("/memories")
async def create_memory(payload: MemoryCreate, request: Request):
    """家属端录入一条记忆（默认 source=family、家属可见、直接可用）"""
    if not (payload.text or "").strip():
        return api_error("memory_empty")
    try:
        entry = _store(request).add(
            elder_id=payload.elder_id,
            text=payload.text,
            kind=payload.kind,
            tags=payload.tags,
            source=payload.source,
            happened_at=payload.happened_at,
            visible_to_family=payload.visible_to_family,
        )
    except ValueError as exc:
        return api_error("invalid_request", str(exc))
    return JSONResponse(content={"memory": entry.to_dict(), "notice": "已记住，之后对话里会自然用到"})


@router.patch("/memories/{memory_id}")
async def update_memory(memory_id: str, payload: MemoryUpdate, request: Request):
    if payload.text is not None and not payload.text.strip():
        return api_error("memory_empty")
    try:
        entry = _store(request).update(
            memory_id,
            text=payload.text,
            kind=payload.kind,
            tags=payload.tags,
            happened_at=payload.happened_at,
            visible_to_family=payload.visible_to_family,
        )
    except ValueError as exc:
        return api_error("invalid_request", str(exc))
    if not entry:
        return api_error("memory_not_found")
    return JSONResponse(content={"memory": entry.to_dict()})


@router.delete("/memories/{memory_id}")
async def delete_memory(memory_id: str, request: Request):
    """单条删除（设计方案要求：记忆库支持单条删除）"""
    removed = _store(request).delete(memory_id)
    if not removed:
        return api_error("memory_not_found")
    return JSONResponse(content={"ok": True, "notice": "已删除，对话里不会再提到它"})


@router.post("/memories/clear")
async def clear_memories(payload: ClearRequest, request: Request):
    """一键清空（设计方案要求）。删的是记忆条目；自动抽取的开关保持原样"""
    removed = _store(request).clear(payload.elder_id)
    return JSONResponse(
        content={"ok": True, "removed": removed, "notice": "这位老人的记忆已清空"}
    )


@router.post("/memories/review")
async def review_memory(payload: MemoryReview, request: Request):
    """复核自动整理的条目：通过 → 可用；否决 → 保留痕迹但不再使用"""
    entry = _store(request).review(payload.id, approve=payload.approve)
    if not entry:
        return api_error("memory_not_found")
    return JSONResponse(
        content={
            "memory": entry.to_dict(),
            "notice": "已通过，之后可以用它主动关心" if payload.approve else "已否决，不会再使用",
        }
    )


@router.get("/memories/settings")
async def get_memory_settings(
    request: Request,
    elder_id: str = Query(default=DEFAULT_ELDER_ID, alias="elderId"),
):
    return JSONResponse(content={"settings": _store(request).settings_for(elder_id).to_dict()})


@router.put("/memories/settings")
async def update_memory_settings(payload: MemorySettingsUpdate, request: Request):
    """开关"从聊天里自动整理记忆"。**默认关**，开启即视为已明确告知本人"""
    settings = _store(request).update_settings(payload.elder_id, auto_extract=payload.auto_extract)
    return JSONResponse(content={"settings": settings.to_dict()})


@router.get("/memories/topics")
async def memory_topics(
    request: Request,
    elder_id: str = Query(default=DEFAULT_ELDER_ID, alias="elderId"),
    limit: int = Query(default=5, ge=1, le=20),
):
    """L3 的用法：这位老人能聊什么（按偏好权重排序）。将来主动关怀从这里取素材"""
    return JSONResponse(
        content={
            "elderId": elder_id,
            "topics": topics(_store(request), elder_id, limit=limit),
        }
    )
