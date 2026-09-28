"""会话编排：上下文组装 → 调模型 → 风格后处理 → 事件产出"""

from .events import HEARTBEAT, frame
from .service import ChatService, StickerExtractor

__all__ = ["HEARTBEAT", "frame", "ChatService", "StickerExtractor"]
