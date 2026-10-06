"""比邻AI · 音频下发（合成音频的暂存 + 短期签名 URL）

## 为什么需要签名 URL，而不是普通鉴权端点

端侧播音频用的是 `uni.createInnerAudioContext().src`（App）或 `<audio>`（H5），
**两者都带不了 `Authorization` 请求头** —— 这是本项目的硬约束
（`server/app/auth.py` 的 `extract_token()` 只从请求头取 token）。

所以音频走**短期签名 URL**：把"谁能取、能取多久"编进 URL 本身，
播放器直接 `src = url` 就能拉，不需要任何请求头。
这也是行业常规做法（S3 预签名 URL 同理），不是本项目自创。

## 签名怎么算

`HMAC-SHA256(key, f"{audio_id}.{expires_at}")`，取前 32 位 hex。
- key 优先用 `BILIN_AUDIO_SECRET`；没配则**从 API_TOKENS 派生**（同一个部署的密钥材料，
  不必让运维多配一个变量）；都没有则随机生成一个进程级密钥
  （**后果：进程重启后旧 URL 全失效**，这是可接受的——音频本来就只活几分钟）。
- 校验用 `hmac.compare_digest`（常量时间，避免用 `==` 泄露前缀）。

## 暂存策略（刻意从简）

- **只在内存里**存音频字节，带 TTL（默认 10 分钟）与总量上限（默认 64MB）。
- 为什么不落磁盘/对象存储：音频是**一次性**的（老人听完就没用），
  落盘要考虑清理与隐私（老人语音属敏感信息），内存 + TTL 是最不容易出错的选择。
- 为什么不做多进程共享：单进程原型阶段够用；要横向扩展时把 `_STORE` 换成 Redis/S3 即可，
  **签名与接口形状不用改**。

## 隐私

老人语音是敏感信息（PIPL）。这里做了三件事：
1. 不落磁盘（进程退出即消失）；
2. 短期签名（默认 10 分钟），过期后 URL 失效；
3. `audio_id` 是随机 hex，**不含任何老人/会话标识**，日志里也不打内容。
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import threading
import time

logger = logging.getLogger(__name__)

# 音频存活时长（秒）—— 老人听完一句就用不到了，10 分钟足够重试
DEFAULT_TTL_S = 600
# 内存里最多留多少音频字节（超过就丢弃最旧的）
DEFAULT_MAX_BYTES = 64 * 1024 * 1024
# 签名有效期比 TTL 略短：给"取到一半过期"留点余量
SIGN_TTL_S = 600


class AudioStore:
    """进程内音频暂存：`put(bytes) -> audio_id`，`get(audio_id) -> bytes|None`。"""

    def __init__(self, ttl_s: int = DEFAULT_TTL_S, max_bytes: int = DEFAULT_MAX_BYTES):
        self.ttl_s = ttl_s
        self.max_bytes = max_bytes
        self._items: dict[str, tuple[float, bytes]] = {}
        self._lock = threading.Lock()
        self._total = 0

    def put(self, data: bytes, ttl_s: int | None = None) -> str:
        if not data:
            return ""
        audio_id = secrets.token_hex(16)          # 随机、不含任何业务标识
        expire_at = time.time() + (ttl_s or self.ttl_s)
        with self._lock:
            self._sweep_locked()
            self._items[audio_id] = (expire_at, bytes(data))
            self._total += len(data)
            self._enforce_limit_locked()
        return audio_id

    def get(self, audio_id: str) -> bytes | None:
        if not audio_id:
            return None
        with self._lock:
            item = self._items.get(audio_id)
            if item is None:
                return None
            expire_at, data = item
            if expire_at < time.time():
                self._items.pop(audio_id, None)
                self._total -= len(data)
                return None
            return data

    def stats(self) -> dict:
        with self._lock:
            return {"items": len(self._items), "bytes": self._total, "ttlSeconds": self.ttl_s}

    # ------------------------------------------------------------------ 内部

    def _sweep_locked(self) -> None:
        now = time.time()
        for key in [k for k, (expire_at, _) in self._items.items() if expire_at < now]:
            data = self._items.pop(key)[1]
            self._total -= len(data)

    def _enforce_limit_locked(self) -> None:
        """超上限就丢**最旧的**（音频是一次性的，丢旧的比丢新的合理）。"""
        if self._total <= self.max_bytes:
            return
        for key in sorted(self._items, key=lambda k: self._items[k][0]):
            if self._total <= self.max_bytes:
                break
            data = self._items.pop(key)[1]
            self._total -= len(data)


_STORE = AudioStore()


def get_store() -> AudioStore:
    return _STORE


def _signing_key(settings=None) -> bytes:
    """签名密钥：优先专用变量 → 从 API_TOKENS 派生 → 进程级随机。"""
    secret = (os.environ.get("BILIN_AUDIO_SECRET") or "").strip()
    if secret:
        return secret.encode("utf-8")
    tokens = ""
    if settings is not None:
        tokens = getattr(settings, "api_tokens", "") or ""
    tokens = tokens or os.environ.get("API_TOKENS", "")
    if tokens:
        # 派生而不是直接用：签名密钥不该等于 API token（泄露签名的危害面要更小）
        return hashlib.sha256(("bilin-audio:" + tokens).encode("utf-8")).digest()
    # 都没有：进程级随机（重启后旧 URL 失效，可接受）
    global _FALLBACK_KEY
    if _FALLBACK_KEY is None:
        _FALLBACK_KEY = secrets.token_bytes(32)
        logger.info("未配置 BILIN_AUDIO_SECRET / API_TOKENS，音频签名改用进程级随机密钥（重启后旧 URL 失效）")
    return _FALLBACK_KEY


_FALLBACK_KEY: bytes | None = None


def sign(audio_id: str, expires_at: int, settings=None) -> str:
    message = ("%s.%d" % (audio_id, expires_at)).encode("utf-8")
    return hmac.new(_signing_key(settings), message, hashlib.sha256).hexdigest()[:32]


def verify(audio_id: str, expires_at: int, signature: str, settings=None) -> tuple[bool, str]:
    """返回 (是否有效, 原因)。原因用于日志，不下发给端侧（避免泄露校验细节）。"""
    try:
        expire = int(expires_at)
    except (TypeError, ValueError):
        return False, "过期时间不是整数"
    if expire < int(time.time()):
        return False, "签名已过期"
    if not signature:
        return False, "缺少签名"
    expected = sign(audio_id, expire, settings)
    if not hmac.compare_digest(expected, str(signature)):
        return False, "签名不匹配"
    return True, ""


def build_audio_url(audio_id: str, settings=None, ttl_s: int = SIGN_TTL_S) -> str:
    """拼出端侧可直接给播放器用的 URL（**无需请求头**）。"""
    expires_at = int(time.time()) + max(30, ttl_s)
    signature = sign(audio_id, expires_at, settings)
    return "/v1/audio/%s?expires=%d&sig=%s" % (audio_id, expires_at, signature)
