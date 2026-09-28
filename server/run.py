"""
比邻AI · agent 服务启动入口

    cd server
    .venv\\Scripts\\python.exe run.py        # Windows
    .venv/bin/python run.py                  # Linux / macOS

等价于：uvicorn app.main:app --host <HOST> --port <PORT>
"""

from __future__ import annotations

import sys

import uvicorn

from app.config import get_settings


def _force_utf8_output() -> None:
    """Windows 下 stdout 被重定向（管道/日志文件）时默认走 GBK，中文日志会乱码。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):  # pragma: no cover
            pass


def main() -> None:
    _force_utf8_output()
    settings = get_settings()
    print("比邻AI agent 服务")
    print("  地址   : http://" + settings.host + ":" + str(settings.port))
    print("  自检   : http://" + settings.host + ":" + str(settings.port) + "/healthz")
    print("  文档   : http://" + settings.host + ":" + str(settings.port) + "/docs")
    print("  模型   : " + settings.resolved_provider + " / " + settings.llm_model)
    print("  密钥   : " + settings.masked_api_key())
    print("")
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
    )


if __name__ == "__main__":
    main()
