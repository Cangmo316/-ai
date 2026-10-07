"""
比邻AI · 按账号解析 LLM Provider

## 为什么需要这一层

需求：「智能体设置里可以选模型 —— 默认比邻AI（服务端配置的那个），
或者填第三方模型的 API URL / API KEY / 模型名称」。

但服务端的 LLM 原来是**一个全局单例**（`main.py` 里 `build_provider(config)` 建一次，
所有账号共用）。所以"每个账号一套模型配置"必须有一层按账号解析的入口，
否则界面填了也不会生效 —— 那才是真的糊弄人。

## 设计要点

1. **惰性 + 缓存**：只有真的被某个账号用到才去建 provider，建好缓存住；
   配置一变就丢缓存（按 `updatedAt` 失效）。
2. **失败不炸**：自定义配置写错了（URL 打不开、key 无效）**不能让整个服务挂**，
   退回内置 provider，并把原因记下来供界面显示。
3. **仅自定义模式才覆盖**：`mode=builtin` 直接给内置 provider。

## 为什么不在每次请求里新建

`OpenAICompatProvider` 内部要建 httpx 客户端；每轮对话新建一个既慢又容易漏关连接。
按"账号 + 配置指纹"缓存是划算的。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .base import LLMProvider
from .openai_compat import OpenAICompatProvider
from .overrides import MODE_CUSTOM, ModelOverrideStore

logger = logging.getLogger(__name__)


@dataclass
class ResolvedProvider:
    """解析结果：给谁用、用的哪个 provider、有没有降级。"""

    provider: LLMProvider
    #: 是否用了账号自己的配置
    custom: bool = False
    #: 降级原因（自定义配置不可用时填，界面据此提示）
    fallback_reason: str = ""
    #: 配置指纹，仅用于缓存比对（不参与相等性）
    fingerprint: str = field(default="", repr=False, compare=False)


@dataclass
class ProviderResolver:
    """
    账号 → LLMProvider。

    @param builtin 服务端按 .env 建好的那个 provider（兜底用）
    @param store   账号覆盖存储
    @param settings 用于自定义 provider 的超时/温度等参数（沿用内置那套，不另开一套配置）
    """

    builtin: LLMProvider
    store: ModelOverrideStore
    settings: object | None = None
    _cache: dict[str, ResolvedProvider] = field(default_factory=dict)

    def resolve(self, account_id: str) -> ResolvedProvider:
        key = str(account_id or "").strip()
        if not key:
            return ResolvedProvider(provider=self.builtin)

        override = self.store.get(key)
        if not override.is_custom:
            return ResolvedProvider(provider=self.builtin)

        # 配置指纹：任何一项变了都要重建（api_key 参与指纹，换 key 立刻生效）
        fingerprint = "|".join([
            key, override.base_url, override.model, override.api_key, override.updated_at
        ])
        cached = self._cache.get(key)
        if cached is not None and cached.fingerprint == fingerprint:
            return cached

        resolved = self._build(key, override, fingerprint)
        self._cache[key] = resolved
        return resolved

    def invalidate(self, account_id: str = "") -> None:
        """配置变了之后调一下（不调也行，指纹会兜住）。"""
        key = str(account_id or "").strip()
        if key:
            self._cache.pop(key, None)
        else:
            self._cache.clear()

    # ------------------------------------------------------------------ 内部

    def _build(self, account_id: str, override, fingerprint: str) -> ResolvedProvider:
        problems = []
        if not override.base_url:
            problems.append("没填 API URL")
        if not override.model:
            problems.append("没填模型名称")
        if not override.api_key:
            problems.append("没填 API KEY")

        if problems:
            reason = "自定义模型配置不完整：" + "、".join(problems)
            logger.warning("%s（账号 %s），暂用内置模型", reason, account_id)
            return ResolvedProvider(provider=self.builtin, custom=False, fallback_reason=reason)

        settings = self.settings
        try:
            provider = OpenAICompatProvider(
                base_url=override.base_url,
                api_key=override.api_key,
                model=override.model,
                # 超时/温度/上限沿用内置那套：不在界面上再开四个输入框
                timeout=getattr(settings, "llm_timeout", 60.0),
                temperature=getattr(settings, "llm_temperature", 0.7),
                max_tokens=getattr(settings, "llm_max_tokens", 512),
            )
        except Exception as exc:  # noqa: BLE001 —— 配置写错不能让服务挂
            reason = "自定义模型创建失败：%s" % exc
            logger.exception("%s（账号 %s）", reason, account_id)
            return ResolvedProvider(provider=self.builtin, custom=False, fallback_reason=reason)

        resolved = ResolvedProvider(provider=provider, custom=True, fingerprint=fingerprint)
        logger.info(
            "账号 %s 使用自定义模型：%s @ %s", account_id, override.model, override.base_url
        )
        return resolved
