"""比邻AI · 识图（读医院单据的照片）与文档解析（读 PDF）"""

from .gateway import (
    ALLOWED_MIME,
    DEFAULT_MODEL,
    DEFAULT_PROMPT,
    MAX_IMAGE_BYTES,
    NullVisionProvider,
    QwenVisionProvider,
    VisionProvider,
    VisionResult,
    build_vision_provider,
    detect_mime,
    is_pdf,
)

__all__ = [
    "ALLOWED_MIME",
    "DEFAULT_MODEL",
    "DEFAULT_PROMPT",
    "MAX_IMAGE_BYTES",
    "NullVisionProvider",
    "QwenVisionProvider",
    "VisionProvider",
    "VisionResult",
    "build_vision_provider",
    "detect_mime",
    "is_pdf",
]
