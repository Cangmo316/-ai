"""康养知识库：读取、校验、按人群匹配"""

from .loader import (
    KnowledgeBase,
    KnowledgeEntry,
    KnowledgeError,
    load_knowledge,
    validate_knowledge,
)

__all__ = [
    "KnowledgeBase",
    "KnowledgeEntry",
    "KnowledgeError",
    "load_knowledge",
    "validate_knowledge",
]
