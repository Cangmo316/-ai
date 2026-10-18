"""
比邻AI · 中文相对日期解析

## 为什么需要它

需求：「这些要记录下来，在后续的标记日期里再次提出来」。
老人说的"下周二去复查""后天闺女来"必须能变成**具体日期**，
否则第二天没法主动提起这件事。

## 为什么自己写而不是装库

项目零第三方依赖。而且这里的需求很窄：只要识别老人常用的几种说法。
装 dateparser 那种库反而会引入一堆用不到的语言规则。

## 一个刻意的保守取向

**解析不出来就返回 None，绝不猜。**
猜错日期会让智能体在错误的日子提错误的事（"您今天该去复查吧"——
人家根本没约），这比不提更糟。所以宁可不识别。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

#: 星期几的中文 → weekday() 的 0=周一
_WEEKDAYS = {
    "一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6,
    "1": 0, "2": 1, "3": 2, "4": 3, "5": 4, "6": 5, "7": 6,
}

#: 固定偏移的说法
_OFFSETS = {
    "今天": 0, "今日": 0, "今儿": 0,
    "明天": 1, "明日": 1, "明儿": 1,
    "后天": 2,
    "大后天": 3,
}

_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6,
        "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12}


@dataclass
class ParsedDate:
    """解析结果。"""

    day: date
    #: 原文里对应的时间片段（用于回访时复述）
    raw: str


def _to_int(text: str) -> int | None:
    text = str(text or "").strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    return _NUM.get(text)


def parse_when(text: str, today: date) -> ParsedDate | None:
    """从一句话里解析出日期。解析不出返回 None（保守，见模块注释）。"""
    body = str(text or "").strip()
    if not body:
        return None

    # ① 具体日期：3月15号 / 3月15日 / 15号
    m = re.search(r"(\d{1,2}|[一二三四五六七八九十]{1,3})\s*月\s*(\d{1,2})\s*[号日]", body)
    if m:
        month = _to_int(m.group(1))
        day_num = _to_int(m.group(2))
        if month and day_num and 1 <= month <= 12 and 1 <= day_num <= 31:
            # 跨年：说的月份比现在早很多，就当下一年
            year = today.year if month >= today.month else today.year + 1
            try:
                return ParsedDate(day=date(year, month, day_num), raw=m.group(0))
            except ValueError:
                return None

    # ② 只有日号：15号 / 15日（当本月/下月）
    m = re.search(r"(\d{1,2})\s*[号日]", body)
    if m:
        day_num = int(m.group(1))
        if 1 <= day_num <= 31:
            for month_offset in (0, 1):
                month = today.month + month_offset
                year = today.year
                if month > 12:
                    month -= 12
                    year += 1
                try:
                    candidate = date(year, month, day_num)
                except ValueError:
                    continue
                # 只说"15号"时，已过去的日期更可能是指下个月
                if candidate >= today:
                    return ParsedDate(day=candidate, raw=m.group(0))

    # ③ 下周X / 这周X / 周X / 星期X / 礼拜X
    m = re.search(r"(下下|下|这|本)?\s*(?:周|星期|礼拜)\s*([一二三四五六日天1-7])", body)
    if m:
        prefix = m.group(1) or ""
        target = _WEEKDAYS.get(m.group(2))
        if target is not None:
            # 本周一 = 0
            monday = today - timedelta(days=today.weekday())
            if prefix in ("下",):
                monday += timedelta(days=7)
            elif prefix == "下下":
                monday += timedelta(days=14)
            candidate = monday + timedelta(days=target)
            # 没写"下"但日期已过，按"下一个"算（口语里"周三去"通常是下一个周三）
            if not prefix and candidate < today:
                candidate += timedelta(days=7)
            return ParsedDate(day=candidate, raw=m.group(0))

    # ④ 相对说法：明天 / 后天 / N天后 / N天以后
    for word, offset in _OFFSETS.items():
        if word in body:
            return ParsedDate(day=today + timedelta(days=offset), raw=word)

    m = re.search(r"(\d{1,2}|[一二三四五六七八九十]{1,2})\s*天\s*(?:以)?后", body)
    if m:
        days = _to_int(m.group(1))
        if days is not None and 1 <= days <= 90:
            return ParsedDate(day=today + timedelta(days=days), raw=m.group(0))

    m = re.search(r"(下一?个?\s*月)\s*(\d{1,2})\s*[号日]", body)
    if m:
        month = today.month + 1
        year = today.year
        if month > 12:
            month = 1
            year += 1
        try:
            return ParsedDate(day=date(year, month, int(m.group(2))), raw=m.group(0))
        except ValueError:
            return None

    return None


def is_future(parsed: ParsedDate | None, today: date) -> bool:
    """是否是将来的日子（今天及以后）。"""
    return parsed is not None and parsed.day >= today


def human_day(target: date, today: date) -> str:
    """把日期说成人话（"今天""明天""下周二"），用于回访时的自然表达。"""
    delta = (target - today).days
    if delta == 0:
        return "今天"
    if delta == 1:
        return "明天"
    if delta == 2:
        return "后天"
    if -1 <= delta <= 6:
        names = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
        return ("上周" if delta < 0 else "") + names[target.weekday()] if delta < 0 else names[target.weekday()]
    return "%d月%d号" % (target.month, target.day)
