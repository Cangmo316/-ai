"""智能体工具层。

对外只暴露注册表与执行入口（见 `registry.py`）。
"""

from .registry import (
    BY_NAME,
    SPECS,
    ToolContext,
    ToolSpec,
    execute,
    openai_tools,
)

__all__ = ["BY_NAME", "SPECS", "ToolContext", "ToolSpec", "execute", "openai_tools"]
