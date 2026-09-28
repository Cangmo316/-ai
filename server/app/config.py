"""
比邻AI · 服务端配置

设计取舍：
- **不引 python-dotenv**：`.env` 的语法在本项目里只用得到 `KEY=VALUE` 与 `#` 注释，
  二十行就能解析完；少一个依赖，部署时少一个坑（仓库约定「优先开源免费、能不加就不加」）。
- `.env` 已在 `.gitignore` 里，**key 永远不进仓库**；`.env.example` 只放变量名与注释。
- 环境变量优先级高于 `.env` 文件，方便容器/计划任务注入而不改文件。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = SERVER_DIR / ".env"


def load_env_file(path: Path | None = None, override: bool = False) -> dict[str, str]:
    """极简 .env 解析：支持 `KEY=VALUE`、`#` 注释、`export ` 前缀、成对引号。

    已存在的环境变量默认**不覆盖**（真实环境优先于文件）。
    """
    target = path or ENV_PATH
    loaded: dict[str, str] = {}
    if not target.exists():
        return loaded
    for raw in target.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if not key:
            continue
        loaded[key] = value
        if override or key not in os.environ:
            os.environ[key] = value
    return loaded


def _env_str(key: str, default: str) -> str:
    value = os.environ.get(key)
    return default if value is None or value == "" else value


def _env_float(key: str, default: float) -> float:
    try:
        return float(_env_str(key, str(default)))
    except ValueError:
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(float(_env_str(key, str(default))))
    except ValueError:
        return default


def _env_list(key: str, default: list[str]) -> list[str]:
    raw = os.environ.get(key)
    if not raw:
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass
class Settings:
    """服务运行期配置。字段名与 .env 变量一一对应。"""

    # ── 模型 ──────────────────────────────────────────────
    # auto：有 key 就走真实模型，没 key 就用 fake（保证链路永远能跑通）
    llm_provider: str = "auto"  # auto | openai_compat | fake
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_timeout: float = 30.0
    llm_temperature: float = 0.8
    llm_max_tokens: int = 300
    # 送进模型的历史轮数（不含本轮）。P2 接三层记忆后会换成相关性检索
    history_turns: int = 8
    # SSE 心跳间隔（秒）。作用不只是防代理掐连接：端侧有 20s 首字节看门狗，
    # 用推理模型时首 token 可能要等几十秒，没有心跳端侧会直接放弃
    sse_heartbeat_seconds: float = 10.0

    # ── 人设 ──────────────────────────────────────────────
    default_persona_id: str = "p_son"

    # ── HTTP ─────────────────────────────────────────────
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: list[str] = field(default_factory=lambda: ["*"])
    log_level: str = "info"

    @classmethod
    def from_env(cls, env_path: Path | None = None) -> "Settings":
        load_env_file(env_path)
        return cls(
            llm_provider=_env_str("LLM_PROVIDER", "auto").lower(),
            llm_base_url=_env_str("LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip("/"),
            llm_api_key=_env_str("LLM_API_KEY", ""),
            llm_model=_env_str("LLM_MODEL", "deepseek-chat"),
            llm_timeout=_env_float("LLM_TIMEOUT", 30.0),
            llm_temperature=_env_float("LLM_TEMPERATURE", 0.8),
            llm_max_tokens=_env_int("LLM_MAX_TOKENS", 300),
            history_turns=_env_int("CHAT_HISTORY_TURNS", 8),
            sse_heartbeat_seconds=_env_float("SSE_HEARTBEAT_SECONDS", 10.0),
            default_persona_id=_env_str("DEFAULT_PERSONA_ID", "p_son"),
            host=_env_str("HOST", "127.0.0.1"),
            port=_env_int("PORT", 8000),
            cors_origins=_env_list("CORS_ORIGINS", ["*"]),
            log_level=_env_str("LOG_LEVEL", "info"),
        )

    # ── 派生属性 ──────────────────────────────────────────

    @property
    def resolved_provider(self) -> str:
        """把 auto 解析成具体实现。"""
        if self.llm_provider in ("openai_compat", "fake"):
            return self.llm_provider
        return "openai_compat" if self.llm_api_key else "fake"

    @property
    def uses_real_model(self) -> bool:
        return self.resolved_provider != "fake"

    def masked_api_key(self) -> str:
        """给 /healthz 与启动日志用：只露尾巴，绝不回显整把 key。"""
        key = self.llm_api_key
        if not key:
            return "(未配置)"
        if len(key) <= 8:
            return "****"
        return key[:4] + "****" + key[-4:]


_settings: Settings | None = None


def get_settings(reload: bool = False) -> Settings:
    global _settings
    if _settings is None or reload:
        _settings = Settings.from_env()
    return _settings
