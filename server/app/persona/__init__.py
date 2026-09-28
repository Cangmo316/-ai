"""人设与话术模板（产品性格的工程化落地）"""

from .prompts import DEFAULT_PERSONAS, Persona, PersonaRegistry, build_system_prompt
from .stickers import STICKER_TOKENS, is_allowed_sticker

__all__ = [
    "DEFAULT_PERSONAS",
    "Persona",
    "PersonaRegistry",
    "build_system_prompt",
    "STICKER_TOKENS",
    "is_allowed_sticker",
]
