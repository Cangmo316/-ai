"""
比邻AI · 主动关心

需求：「智能体需要有人的好奇心，在一些时候需要问老人一些日程的问题，
比如吃了什么，有没有遇到特别的事，有没有什么想做的事，每天要主动问1-2次，
这些要记录下来，在后续的标记日期里再次提出来，让老人真正认为智能体是在乎他的」

两块东西：

  · **主动问**（service.ask_now）—— 一天最多 2 次，按时段挑问题，
    进对话 + 推送，不追问不回的人
  · **到期回访**（service.followup_lines）—— 他说过"下周二去复查"就记下来，
    到那天自然地问一句"今天去复查了吧"

为什么回访比提问更重要：老人感到被在乎，往往不是因为被问了，
而是因为**被记住**。
"""

from .dates import ParsedDate, human_day, is_future, parse_when
from .models import (
    FOLLOWUP_DONE,
    FOLLOWUP_DROP,
    FOLLOWUP_DUE,
    FOLLOWUP_PENDING,
    TOPIC_DAY,
    TOPIC_EAT,
    TOPIC_EVENT,
    TOPIC_FOLLOWUP,
    TOPIC_WISH,
    CareAsk,
    FollowUp,
)
from .service import (
    MAX_PER_DAY,
    MIN_GAP_HOURS,
    QUIET_AFTER_CHAT_MINUTES,
    WAKE_END,
    WAKE_START,
    CareService,
)
from .store import CareStore, default_care_root
from .topics import pick_question, topic_label

__all__ = [
    "CareAsk",
    "CareService",
    "CareStore",
    "FOLLOWUP_DONE",
    "FOLLOWUP_DROP",
    "FOLLOWUP_DUE",
    "FOLLOWUP_PENDING",
    "FollowUp",
    "MAX_PER_DAY",
    "MIN_GAP_HOURS",
    "ParsedDate",
    "QUIET_AFTER_CHAT_MINUTES",
    "TOPIC_DAY",
    "TOPIC_EAT",
    "TOPIC_EVENT",
    "TOPIC_FOLLOWUP",
    "TOPIC_WISH",
    "WAKE_END",
    "WAKE_START",
    "default_care_root",
    "human_day",
    "is_future",
    "parse_when",
    "pick_question",
    "topic_label",
]
