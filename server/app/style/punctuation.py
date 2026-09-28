"""
比邻AI · 「句末不加句号」后处理（设计方案 §3.1 三层保险之二）

规则来源（设计方案原文）：
    - 末尾为「。」或英文「.」→ 删除
    - 小数保护：/(\\d)\\.(\\d)/ 不处理（如 2.5mg）
    - 缩写保护：Mr. / No. / kg. 不处理
    - 省略号「…」「...」保留（表示迟疑/亲昵）
    - 多句处理：agent 回复多句时，句号替换为换行

**为什么做成流式处理器而不是一个普通函数**：
回复是逐 token 流式下发的。如果只在全量文本上跑一次后处理，就必须先把整段回复攒完再发——
老人端的「逐字说话」效果没了，首响也会从 1 秒退到好几秒。但逐 token 直接替换又判不了
「2.5」这种被切开的小数（"2" | "." | "5" 分三次到达）。

统一策略：**凡是"发出去了才发现不该发"的东西，一律先扣住**——

| 扣住的东西 | 为什么 |
|---|---|
| 句号（。/.） | 要等下一个字符才能判断是小数、缩写还是句末 |
| 换行 | 句号转出来的换行，如果后面没内容了，就会在气泡里留一个空行 |
| 空白 | 同上，尾随空格也没意义 |

这样既保住逐字流（正常内容一个字都不延迟），又保证「流式拼出来的文本」和
「整段一次性处理」逐字一致。`apply_style()` 只是后者的调用形式，两条路径共用同一实现，
不允许出现「打字时一个样、降级后另一个样」的分叉。

**已知取舍**：半角点夹在字母中间（`abc.def`、网址）会被当成句末转成换行。
理由：① prompt 已明确禁止输出网址；② 老人聊天里几乎不出现这种形态；
③ 要正确识别域名/版本号得引入更复杂的规则，收益不抵风险。
`tests/test_style.py` 里对这条行为有 characterization 用例，将来要改是有意识的改动。
"""

from __future__ import annotations

import re

# 全角句号：中文语境下永远是句末，不需要看上下文
FULL_STOP = "。"
# 半角点：可能是小数、缩写、省略号的一部分，必须看前后文
DOT = "."
ELLIPSIS = "…"

# 常见缩写（小写比较）。命中时点号保留：No.3 / kg. / Mr.Wang
ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "no", "vs", "etc", "st", "jr", "sr",
    "kg", "g", "mg", "cm", "mm", "ml", "l", "approx", "fig", "vol",
}

# 首字母缩写：U.S. / e.g. / a.m.（一个字母 + 点，重复出现）
_INITIALISM = re.compile(r"^(?:[a-z]\.)+[a-z]?$")
# 尾部词窗口：判断缩写只需要看最后一个词
_WORD_TAIL = re.compile(r"[A-Za-z][A-Za-z.]*$")
# 尾部字符窗口
_TAIL_WINDOW = 64
# 空白：行首、断句后、末尾都要丢掉
_BLANK = " \t\u3000"


class StyleStreamer:
    """按字符喂入，按字符吐出已经合规的文本。

    用法（服务端流式下发）：

        s = StyleStreamer()
        for delta in llm_stream:
            chunk = s.feed(delta)
            if chunk:
                send_token(chunk)
        tail = s.flush()
    """

    def __init__(self) -> None:
        self._pending_dots = 0            # 挂起的半角点个数（>=2 判为省略号）
        self._pending_full_stop = False   # 挂起的全角句号
        self._pending_break = False       # 挂起的换行（等真的还有内容再吐）
        self._pending_blanks = ""         # 挂起的空白（等真的有内容再吐）
        self._tail = ""                   # 最近吐出的字符窗口（判缩写/小数用）
        self._last_out = ""               # 最后一个吐出的字符（""=还没吐过）

    # ---------------------------------------------------------------- 入口

    def feed(self, delta: str) -> str:
        """送入一段增量文本，返回已经可以安全下发的部分（可能为空串）。"""
        if not delta:
            return ""
        out: list[str] = []
        for ch in delta:
            self._consume(ch, out)
        return "".join(out)

    def flush(self) -> str:
        """流结束：单个句号与所有挂起的空白/换行丢弃，省略号补吐出来。"""
        out: list[str] = []
        if self._pending_dots >= 2:
            self._release_pending(out)
            self._emit(out, DOT * self._pending_dots)
        self._pending_dots = 0
        self._pending_full_stop = False
        self._pending_break = False
        self._pending_blanks = ""
        return "".join(out)

    # ---------------------------------------------------------------- 内部

    def _consume(self, ch: str, out: list[str]) -> None:
        # 有挂起的句号时，先用当前字符把它结算掉
        if self._pending_dots or self._pending_full_stop:
            if ch == DOT:
                if self._pending_full_stop:
                    # 「。」后面又跟了半角点：先把句号结算掉，再开始数点
                    self._pending_full_stop = False
                    self._emit_break()
                    self._pending_dots = 1
                else:
                    self._pending_dots += 1
                return
            self._settle_stop(out, lookahead=ch)

        if ch == DOT:
            self._pending_dots = 1
            return
        if ch == FULL_STOP:
            self._pending_full_stop = True
            return
        if ch == ELLIPSIS:
            self._release_pending(out)
            self._emit(out, ch)
            return
        if ch == "\n":
            self._emit_break()
            return
        if ch in _BLANK:
            # 行首空白、断句后的空白都不留；其余先挂起（末尾的会被 flush 丢掉）
            if self._last_out == "" or self._pending_break:
                return
            self._pending_blanks += ch
            return
        self._release_pending(out)
        self._emit(out, ch)

    def _settle_stop(self, out: list[str], lookahead: str | None = None) -> None:
        """结算挂起的句号：保留（小数/缩写/省略号）还是转成换行。"""
        if self._pending_dots:
            count = self._pending_dots
            self._pending_dots = 0
            if count >= 2:
                # 「...」保留原样
                self._release_pending(out)
                self._emit(out, DOT * count)
                return
            if self._is_decimal(lookahead) or self._is_abbreviation():
                self._release_pending(out)
                self._emit(out, DOT)
                return
            self._emit_break()
            return

        if self._pending_full_stop:
            self._pending_full_stop = False
            self._emit_break()

    def _is_decimal(self, lookahead: str | None) -> bool:
        """2.5mg —— 前后都是数字时，这个点不是句末。"""
        if lookahead is None or not lookahead.isdigit():
            return False
        return self._tail[-1:].isdigit()

    def _is_abbreviation(self) -> bool:
        """kg. / Mr. / U.S. / e.g. —— 点号属于缩写词，不转行。"""
        match = _WORD_TAIL.search(self._tail)
        if not match:
            return False
        word = match.group(0).lower().rstrip(".")
        if not word:
            return False
        if word in ABBREVIATIONS:
            return True
        if _INITIALISM.match(word):
            return True
        # 单个字母后面跟点，在中文对话里几乎不可能是句末
        return len(word) == 1 and word.isalpha()

    def _emit(self, out: list[str], text: str) -> None:
        if not text:
            return
        self._tail = (self._tail + text)[-_TAIL_WINDOW:]
        self._last_out = text[-1]
        out.append(text)

    def _emit_break(self) -> None:
        """句号 → 换行（先挂起）：行首不产生空行，连续句号只留一个换行。"""
        self._pending_blanks = ""  # 句末后面的空白没有意义
        if self._last_out in ("", "\n") or self._pending_break:
            return
        self._pending_break = True

    def _release_pending(self, out: list[str]) -> None:
        """真的有内容要吐了：先把挂起的换行/空白吐出去。"""
        if self._pending_break:
            self._pending_break = False
            self._pending_blanks = ""  # 断句后的缩进没有意义
            self._emit(out, "\n")
        if self._pending_blanks:
            blanks = self._pending_blanks
            self._pending_blanks = ""
            self._emit(out, blanks)


def apply_style(text: str) -> str:
    """整体后处理（非流式路径用）。

    与流式共用同一实现，保证两条路径输出逐字一致。
    """
    streamer = StyleStreamer()
    return (streamer.feed(text) + streamer.flush()).strip()
