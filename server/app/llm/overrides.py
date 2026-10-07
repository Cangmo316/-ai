"""
比邻AI · 每个账号的模型覆盖（智能体设置里填的 API URL / KEY / 模型名）

## 为什么存 JSON 文件而不是主库

里面是**明文 API KEY**。主库（sqlite）会被备份、被打包、被拷来拷去，
密钥混在里面等于到处泄漏。单独一个小文件：
  · 可以单独设更严的文件权限
  · 备份时可以单独排除
  · 出问题时删掉一个文件就回退了（不必动 schema）

文件位置：`server/data/llm_overrides.json`（`data/` 已在 .gitignore 里，不会进仓库）。

## 结构

    {
      "a_b62ede07ee85bc31": {
        "mode": "custom",
        "baseUrl": "https://api.deepseek.com/v1",
        "apiKey": "sk-…",
        "model": "deepseek-chat",
        "updatedAt": "2026-10-08T…"
      }
    }

`mode` 只有两个值：
  · `builtin` —— 用服务端配置的那个模型（默认，等于没覆盖）
  · `custom`  —— 用账号自己填的三项

**不存成"没有这条记录"来表示 builtin**：显式写 `mode` 才能区分
"用户明确选择了内置" 和 "用户从没设置过"，产品语义不同。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

MODE_BUILTIN = "builtin"
MODE_CUSTOM = "custom"

#: 覆盖文件默认位置（相对 server/ 目录）
DEFAULT_FILENAME = "llm_overrides.json"


def mask_key(key: str) -> str:
    """密钥脱敏。**绝不能把完整 key 回给端侧**——端侧只是显示。"""
    text = str(key or "")
    if not raw_ok(text):
        return ""
    if len(text) <= 10:
        return text[:2] + "****"
    return text[:6] + "****" + text[-4:]


def raw_ok(text: str) -> bool:
    return len(str(text or "").strip()) >= 8


@dataclass
class ModelOverride:
    """一个账号的模型选择。"""

    mode: str = MODE_BUILTIN
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    updated_at: str = ""

    @property
    def is_custom(self) -> bool:
        return self.mode == MODE_CUSTOM

    def to_public(self) -> dict:
        """给端侧看的形态：**密钥脱敏**，但要带上"是否已配置"供界面判断。"""
        return {
            "mode": self.mode,
            "baseUrl": self.base_url,
            "model": self.model,
            "hasApiKey": raw_ok(self.api_key),
            "apiKeyMasked": mask_key(self.api_key),
            "updatedAt": self.updated_at,
        }

    def to_storage(self) -> dict:
        return {
            "mode": self.mode,
            "baseUrl": self.base_url,
            "apiKey": self.api_key,
            "model": self.model,
            "updatedAt": self.updated_at,
        }


@dataclass
class ModelOverrideStore:
    """
    账号 → 模型覆盖。**内存里持有全量**（就几十条），写盘时整体落。

    为什么不逐条追加：这是配置不是日志，整体写 + 原子替换最简单也最不容易写坏。
    """

    path: Path
    _data: dict[str, ModelOverride] = field(default_factory=dict)

    def load(self) -> int:
        self._data = {}
        if not self.path.exists():
            return 0
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8") or "{}")
        except (OSError, ValueError):
            logger.exception("模型覆盖文件读不动，按空处理：%s", self.path)
            return 0
        if not isinstance(payload, dict):
            return 0
        for account_id, item in payload.items():
            if not isinstance(item, dict):
                continue
            self._data[str(account_id)] = ModelOverride(
                mode=MODE_CUSTOM if item.get("mode") == MODE_CUSTOM else MODE_BUILTIN,
                base_url=str(item.get("baseUrl") or "").strip(),
                api_key=str(item.get("apiKey") or "").strip(),
                model=str(item.get("model") or "").strip(),
                updated_at=str(item.get("updatedAt") or ""),
            )
        return len(self._data)

    def get(self, account_id: str) -> ModelOverride:
        """取某账号的覆盖；没有就返回内置模式（不是 None，调用方少判一次）。"""
        found = self._data.get(str(account_id or ""))
        return found if found is not None else ModelOverride()

    def save(self, account_id: str, override: ModelOverride) -> None:
        key = str(account_id or "").strip()
        if not key:
            raise ValueError("缺少账号 id")
        # 内置模式不落自定义三件套，避免"切回内置但旧 key 还留着"
        if not override.is_custom:
            override = ModelOverride(mode=MODE_BUILTIN, updated_at=override.updated_at)
        self._data[key] = override
        self._flush()

    def clear(self, account_id: str) -> bool:
        key = str(account_id or "").strip()
        if key not in self._data:
            return False
        del self._data[key]
        self._flush()
        return True

    def _flush(self) -> None:
        """原子写：先写临时文件再 replace，避免写一半被读到半截 JSON。"""
        payload = {k: v.to_storage() for k, v in self._data.items()}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle = tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=str(self.path.parent), delete=False, suffix=".tmp"
            )
            try:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            finally:
                handle.close()
            os.replace(handle.name, self.path)
            # 密钥文件：只给当前用户读写
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
        except OSError:
            logger.exception("模型覆盖写盘失败：%s", self.path)


def default_store_path(server_dir: Path | None = None) -> Path:
    base = server_dir or Path(__file__).resolve().parents[2]
    return Path(base) / "data" / DEFAULT_FILENAME
