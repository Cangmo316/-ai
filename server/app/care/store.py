"""
比邻AI · 关心记录的存储

与 wiki 一样用**文件 + 原子写**，理由也一致：
  · 数据量小（一天两三条），不值得为它上数据库
  · 出问题能直接打开文件看，不用连库查
  · 备份时与 wiki 一起带走

目录：`server/data/care/<elder_id>.json`
"""

from __future__ import annotations

import json
import logging
import tempfile
import threading
from pathlib import Path

from .models import CareAsk, FollowUp

logger = logging.getLogger("bilin.care")


def default_care_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "data" / "care"


class CareStore:
    """按老人分文件的关心记录。"""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root else default_care_root()
        self._lock = threading.Lock()

    def _path(self, elder_id: str) -> Path:
        safe = "".join(ch for ch in str(elder_id or "") if ch.isalnum() or ch in "_-")
        if not safe:
            safe = "default"
        return self.root / f"{safe}.json"

    def _load(self, elder_id: str) -> dict:
        path = self._path(elder_id)
        if not path.exists():
            return {"asks": [], "followups": []}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            # 文件坏了不能让关心功能整个挂掉：当作空的，下次写入会覆盖
            logger.warning("关心记录读不出来，按空处理：%s", path)
            return {"asks": [], "followups": []}
        if not isinstance(data, dict):
            return {"asks": [], "followups": []}
        data.setdefault("asks", [])
        data.setdefault("followups", [])
        return data

    def _save(self, elder_id: str, data: dict) -> bool:
        """原子写：临时文件 + replace，避免读到半截 JSON。"""
        path = self._path(elder_id)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=str(path.parent), delete=False, suffix=".tmp"
            )
            try:
                json.dump(data, handle, ensure_ascii=False, indent=1)
                handle.flush()
                temp_name = handle.name
            finally:
                handle.close()
            Path(temp_name).replace(path)
            return True
        except OSError:
            logger.exception("关心记录写入失败：%s", path)
            return False

    # ---------------------------------------------------------------- 提问
    def add_ask(self, ask: CareAsk) -> None:
        with self._lock:
            data = self._load(ask.elder_id)
            data["asks"].append(ask.to_dict())
            # 只留最近 200 条：这是"频率控制 + 最近问过什么"用的，
            # 留太多既没用又会让文件越写越慢
            data["asks"] = data["asks"][-200:]
            self._save(ask.elder_id, data)

    def update_ask(self, ask: CareAsk) -> None:
        with self._lock:
            data = self._load(ask.elder_id)
            for index, item in enumerate(data["asks"]):
                if item.get("id") == ask.id:
                    data["asks"][index] = ask.to_dict()
                    break
            self._save(ask.elder_id, data)

    def asks(self, elder_id: str) -> list[CareAsk]:
        return [CareAsk.from_dict(item) for item in self._load(elder_id).get("asks", [])]

    def count_asks(self, elder_id: str, day: str) -> int:
        return sum(1 for ask in self.asks(elder_id) if ask.day == day)

    def last_ask(self, elder_id: str) -> CareAsk | None:
        items = self.asks(elder_id)
        return items[-1] if items else None

    def recent_asks(self, elder_id: str, limit: int = 5) -> list[CareAsk]:
        return self.asks(elder_id)[-max(1, limit):]

    # ---------------------------------------------------------------- 回访
    def followups(self, elder_id: str) -> list[FollowUp]:
        return [FollowUp.from_dict(item) for item in self._load(elder_id).get("followups", [])]

    def save_followups(self, elder_id: str, items: list[FollowUp]) -> None:
        with self._lock:
            data = self._load(elder_id)
            data["followups"] = [item.to_dict() for item in items]
            self._save(elder_id, data)

    def add_followup(self, item: FollowUp) -> None:
        with self._lock:
            data = self._load(item.elder_id)
            data["followups"].append(item.to_dict())
            self._save(item.elder_id, data)
