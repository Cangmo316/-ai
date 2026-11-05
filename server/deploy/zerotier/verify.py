"""全链路验证：给一个服务器地址，跑完端侧会走的所有路径。

    python server/deploy/zerotier/verify.py http://10.1.1.50:8000 [--token <API_TOKENS>]

为什么要单独一个脚本：
    "healthz 通了" 不等于 "能用"。端侧真实链路是
        healthz → 登录（拿会话 token）→ 带双头调账号接口 → 拉会话 → 对话 → SSE 流式
    其中任何一步断掉，用户看到的现象都是"连不上/进不去"，但原因完全不同。
    这个脚本按顺序跑一遍，把断在哪一步直接指出来。

    SSE 那一步特别重要：ZeroTier 是点对点隧道，MTU 与分片行为和普通网络不同，
    流式对话最容易在这里出问题（表现为"能登录、但AI一直不回话"）。
"""

from __future__ import annotations

import argparse
import json
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

OK = "  ✅"
NG = "  ❌"
WARN = "  ⚠️ "


def call(base, method, path, body=None, session="", token="", stream=False, timeout=60):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    request = urllib.request.Request(base + path, data=data, method=method)
    request.add_header("Content-Type", "application/json; charset=utf-8")
    if token:
        request.add_header("X-API-Token", token)      # 静态门
    if session:
        request.add_header("Authorization", "Bearer " + session)  # 账号身份
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
        raw = response.read().decode("utf-8", "replace")
        return response.status, raw if stream else json.loads(raw), None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw), None
        except Exception:
            return exc.code, raw, None
    except Exception as exc:  # noqa: BLE001
        return 0, None, str(exc)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("address")
    parser.add_argument("--token", default="")
    parser.add_argument("--name", default="张三测试")
    parser.add_argument("--password", default="Bilin@2026")
    args = parser.parse_args()

    base = args.address.strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        base = "http://" + base
    parsed = urlparse(base)
    host, port = parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)

    print("\n=== 0. TCP 可达性（先排除网络层）===")
    try:
        with socket.create_connection((host, port), timeout=8):
            print(f"{OK} {host}:{port} 可连接")
    except Exception as exc:  # noqa: BLE001
        print(f"{NG} {host}:{port} 连不上：{exc}")
        print(f"{WARN} 检查：ZeroTier 是否加入同一网络、服务是否只绑了 ZeroTier 地址、防火墙是否放行")
        return 1

    print("\n=== 1. healthz（必须免鉴权）===")
    status, payload, error = call(base, "GET", "/healthz", timeout=10)
    if status != 200 or not isinstance(payload, dict):
        print(f"{NG} HTTP {status} {error or ''}")
        return 1
    print(f"{OK} 200  {payload.get('service')} v{payload.get('version')}  模型={payload.get('llm', {}).get('model')}")
    if payload.get("llm", {}).get("usesRealModel") is False:
        print(f"{WARN} 服务端用的是 fake 模型（没配密钥），对话会是模板回复")

    print("\n=== 2. 登录 ===")
    status, payload, error = call(base, "POST", "/v1/accounts/login",
                                  {"name": args.name, "password": args.password}, token=args.token)
    if status == 401:
        print(f"{NG} 401 —— 服务端开了 AUTH_MODE=required，但请求没带（或带错了）X-API-Token")
        print(f"{WARN} 用 --token <服务端 /etc/bilin/bilin.env 里的 API_TOKENS> 重跑")
        return 1
    if status != 200:
        print(f"{NG} HTTP {status} {payload or error}")
        return 1
    session = payload["token"]
    account = payload.get("account") or {}
    print(f"{OK} 200  账号 {account.get('name')}（{account.get('number')}）")

    print("\n=== 3. 账号接口（双 token 共存的关键一步）===")
    status, payload, error = call(base, "GET", "/v1/accounts/me", session=session, token=args.token)
    if status != 200:
        print(f"{NG} HTTP {status} {payload or error}")
        print(f"{WARN} 这说明「静态门」把带会话 token 的请求挡住了 —— 服务端 auth.py 不是我改过的版本")
        return 1
    print(f"{OK} 200  {payload.get('account', {}).get('name')}")

    print("\n=== 4. 会话列表 ===")
    status, payload, error = call(base, "GET", "/v1/conversations", session=session, token=args.token)
    if status != 200:
        print(f"{NG} HTTP {status}")
        return 1
    items = payload.get("conversations") or []
    print(f"{OK} 200  {len(items)} 个会话")
    for item in items[:3]:
        print(f"     · {item.get('kind')}  {item.get('id')}")

    print("\n=== 5. 非流式对话 ===")
    started = time.time()
    status, payload, error = call(base, "POST", "/v1/chat/send",
                                  {"text": "我今天出去走了走 心情不错", "personaId": "p_chat"},
                                  session=session, token=args.token, timeout=120)
    elapsed = time.time() - started
    if status != 200:
        print(f"{NG} HTTP {status} {payload or error}")
        return 1
    text = (payload.get("text") or "").replace("\n", " / ")
    print(f"{OK} 200  {elapsed:.1f}s  「{text[:80]}」")

    print("\n=== 6. SSE 流式（ZeroTier 上最容易出问题的一步）===")
    started = time.time()
    status, raw, error = call(base, "POST", "/v1/chat/stream",
                              {"text": "今天有点冷"}, session=session, token=args.token,
                              stream=True, timeout=180)
    elapsed = time.time() - started
    if status != 200:
        print(f"{NG} HTTP {status} {error or ''}")
        return 1
    frames = raw.count("event: token")
    print(f"{OK} 200  {elapsed:.1f}s  token 帧 {frames} 个  以 meta 开头={raw.startswith('event: meta')}")
    if frames == 0:
        print(f"{WARN} 有响应但没有 token 帧 —— 检查是否被中间层缓冲")
        return 1

    print("\n" + "=" * 46)
    print("  全部通过：这个地址可以给 App 用了")
    print("=" * 46)
    print(f"\n  手机端：我的 → 服务器地址 → {base} → 测试连接 → 保存\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
