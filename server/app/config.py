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


_TRUE_VALUES = {"1", "true", "yes", "on", "y", "t"}


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in _TRUE_VALUES


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

    # ── 提醒调度（P1）─────────────────────────────────────
    # 调度器开关：关掉后不再自动投递提醒（测试里常关掉，手动 tick）
    scheduler_enabled: bool = True
    # 后台 tick 间隔（秒）。30 秒足够精确到"分钟级提醒"，也不至于空转
    scheduler_tick_seconds: float = 30.0
    # 是否允许通过 POST /v1/scheduler/tick 手动推进（联调/演示用；**上线前应关掉**）
    scheduler_manual_tick: bool = True
    # 过期宽限：服务没运行时错过的提醒，超过这么久就不再补发
    # （早上 8 点的用药提醒，下午 3 点才开机补发一条"该吃药了"只会添乱）
    reminder_grace_minutes: int = 30
    # 强提醒未响应多久后再响一次，以及最多重复几次
    reminder_repeat_minutes: int = 5
    reminder_max_repeats: int = 1
    # 未响应多久判定为错过（写进任务状态，供家属端看完成情况）
    reminder_miss_minutes: int = 60
    # 弱提醒的时间窗（超过就不发，不顺延）——设计方案 §3.2「弱提醒超窗不顺延」
    weak_reminder_window: tuple[str, str] = ("09:00", "20:00")

    # ── uni-push 2.0（可选的第二通道）───────────────────────
    # uni-push 2.0 的服务端 SDK 只能跑在 uniCloud 云函数里，所以这里配的是"云函数 URL"，
    # 个推的 appkey/mastersecret 留在云函数那侧，不进本服务。
    # 参考实现：server/deploy/unipush-cloudfunction/
    unipush_send_url: str = ""
    # 自定义校验 token（云函数里比对；两边都不填就等于"谁能访问 URL 谁就能发推送"）
    unipush_token: str = ""
    unipush_timeout: float = 10.0
    # 在线时也创建通知栏消息：提醒类消息要"一定响"，代价是前台可能同时看到提醒条与通知
    unipush_force_notification: bool = True

    # ── HTTP ─────────────────────────────────────────────
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: list[str] = field(default_factory=lambda: ["*"])
    log_level: str = "info"

    # ── 鉴权（P1 最小可用版，见 app/auth.py 的"能防/不能防"表）──
    # off      明确关闭（本机开发）
    # auto     配了 API_TOKENS 就强制校验，没配则放行并在启动日志里大声警告（默认）
    # required 强制校验；没配 token 直接启动失败（**上线用这个**）
    auth_mode: str = "auto"
    api_tokens: str = ""

    # ── 落库（P2）──────────────────────────────────────────
    # 默认 memory://：**不落库、重启即清空**。这是刻意的——测试与 CI 必须互不污染，
    # 不能因为跑一次单测就在仓库目录里留一个数据库文件。
    # 要真落库就在 server/.env 里设（见 .env.example）：
    #   memory://                 不落库（测试/CI）
    #   sqlite:///data/bilin.db   标准库 sqlite3，零安装（本机推荐）
    #   postgresql://...          需装驱动（psycopg）；方言差异见 app/storage/db.py
    database_url: str = "memory://"

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
            scheduler_enabled=_env_bool("SCHEDULER_ENABLED", True),
            scheduler_tick_seconds=_env_float("SCHEDULER_TICK_SECONDS", 30.0),
            scheduler_manual_tick=_env_bool("SCHEDULER_MANUAL_TICK", True),
            reminder_grace_minutes=_env_int("REMINDER_GRACE_MINUTES", 30),
            reminder_repeat_minutes=_env_int("REMINDER_REPEAT_MINUTES", 5),
            reminder_max_repeats=_env_int("REMINDER_MAX_REPEATS", 1),
            reminder_miss_minutes=_env_int("REMINDER_MISS_MINUTES", 60),
            weak_reminder_window=(
                _env_str("WEAK_REMINDER_START", "09:00"),
                _env_str("WEAK_REMINDER_END", "20:00"),
            ),
            unipush_send_url=_env_str("UNIPUSH_SEND_URL", ""),
            unipush_token=_env_str("UNIPUSH_TOKEN", ""),
            unipush_timeout=_env_float("UNIPUSH_TIMEOUT", 10.0),
            unipush_force_notification=_env_bool("UNIPUSH_FORCE_NOTIFICATION", True),
            host=_env_str("HOST", "127.0.0.1"),
            port=_env_int("PORT", 8000),
            cors_origins=_env_list("CORS_ORIGINS", ["*"]),
            log_level=_env_str("LOG_LEVEL", "info"),
            auth_mode=_env_str("AUTH_MODE", "auto").lower(),
            api_tokens=_env_str("API_TOKENS", ""),
            database_url=_env_str("DATABASE_URL", "memory://"),
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
