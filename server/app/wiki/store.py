"""
比邻AI · wiki 的文件存储

设计取舍：
  · **一个老人一个目录**：`wiki/<elder_id>/elder.md`、`persona.md`。
    分隔清楚，删某个老人的数据就是删一个目录。
  · **原子写**：先写临时文件再 replace。wiki 会被每轮对话读，
    非原子写会让它读到半截文件（表现为"画像突然空了一半"）。
  · **进程内缓存**：wiki 每轮都要读，磁盘 IO 不该成为对话延迟的一部分。
    缓存按 (elder_id, kind) 存，写入时失效。
  · **失败不影响对话**：所有读写异常都吞掉并记日志，绝不让老人发不出消息。
"""

from __future__ import annotations

import logging
import tempfile
import threading
from pathlib import Path

from .models import (
    WIKIS,
    WikiPage,
    parse_markdown,
)

logger = logging.getLogger("bilin.wiki")

#: 默认放在 server/data/wiki 下 —— 和数据库同一个根，备份时一起带走
def default_wiki_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "data" / "wiki"


class WikiStore:
    """按老人隔离的 Markdown wiki 存储。"""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root else default_wiki_root()
        self._cache: dict[tuple[str, str], WikiPage] = {}
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- 路径
    def _dir_of(self, elder_id: str) -> Path:
        # 老人 id 来自内部（e_1 这类），但仍做一次清洗，防止拼进路径穿越
        safe = "".join(ch for ch in str(elder_id or "") if ch.isalnum() or ch in "_-")
        if not safe:
            safe = "default"
        return self.root / safe

    def path_of(self, elder_id: str, kind: str) -> Path:
        return self._dir_of(elder_id) / f"{kind}.md"

    # ---------------------------------------------------------------- 读
    def load(self, elder_id: str, kind: str, *, use_cache: bool = True) -> WikiPage:
        key = (str(elder_id or ""), kind)
        if use_cache:
            with self._lock:
                hit = self._cache.get(key)
            if hit is not None:
                return hit

        path = self.path_of(elder_id, kind)
        page: WikiPage
        try:
            if path.exists():
                text = path.read_text(encoding="utf-8")
                page = parse_markdown(kind, str(elder_id or ""), text)
            else:
                page = WikiPage.empty(kind, str(elder_id or ""))
        except Exception:  # noqa: BLE001 —— 读失败不能拖垮对话
            logger.exception("读取 wiki 失败：%s", path)
            page = WikiPage.empty(kind, str(elder_id or ""))

        with self._lock:
            self._cache[key] = page
        return page

    def load_all(self, elder_id: str) -> dict[str, WikiPage]:
        """读某个老人的全部 wiki（两套）。"""
        return {kind: self.load(elder_id, kind) for kind in WIKIS}

    # ---------------------------------------------------------------- 写
    def save(self, page: WikiPage) -> bool:
        """原子写入一份 wiki。返回是否成功（失败不抛，只记日志）。"""
        path = self.path_of(page.elder_id, page.kind)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            body = page.to_markdown()
            # 原子写：临时文件 + replace。
            # 直接写目标文件的话，正在读的请求会读到半截内容。
            handle = tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=str(path.parent), delete=False, suffix=".tmp"
            )
            try:
                handle.write(body)
                handle.flush()
                temp_name = handle.name
            finally:
                handle.close()
            Path(temp_name).replace(path)
            with self._lock:
                self._cache[(str(page.elder_id or ""), page.kind)] = page
            return True
        except Exception:  # noqa: BLE001
            logger.exception("写入 wiki 失败：%s", path)
            return False

    def invalidate(self, elder_id: str, kind: str | None = None) -> None:
        """清缓存（人工改了文件后调用）。"""
        with self._lock:
            if kind is None:
                for k in list(self._cache):
                    if k[0] == str(elder_id or ""):
                        del self._cache[k]
            else:
                self._cache.pop((str(elder_id or ""), kind), None)

    # ---------------------------------------------------------------- 摘要
    def summary(self, elder_id: str) -> dict:
        """给 /healthz 与调试用：两份 wiki 各有多少条。"""
        out: dict[str, int] = {}
        for kind in WIKIS:
            page = self.load(elder_id, kind)
            out[kind] = page.total_items()
        return out
