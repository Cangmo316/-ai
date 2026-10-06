"""比邻AI · 文字 → 口型关键帧（viseme cues）

## 这一层干什么

把一句回复文本变成**带时间区间的口型指令**，端侧只做插值并把权重写进形态键
（`face-three.js` 的 `setVisemes`）。契约见 `uni-app/api/README.md` 的 SSE `lipsync` 事件。

## 为什么"字 → viseme"放在后端

`uni-app/` 工程是**零 npm 依赖**，端侧没有拼音表（全仓 grep `pinyin` 为 0 命中）；
把汉字解析放后端，端侧就只需要"按时间插值"这一件小事，逻辑最少、出错面最小。

## ⚠️ 当前实现的诚实边界（不要当成最终形态）

- 时间轴是**按字数等分估算**的（`DEFAULT_CHAR_MS`），**不是真实语音对齐**。
  真 TTS（CosyVoice 2）就绪后，这里应当改成**接收真实字级时间戳**：
  开源 CosyVoice 2 不原生给时间戳（已核实其 `inference_*` 只 yield 音频张量），
  可行路径是 ASR 侧强制对齐（FunASR / WhisperX）或托管版 WS 的 `sentence.words[]`。
  本模块的对外接口（`build_cues`）已经按"时间由外部给"来设计，
  届时**只换数据来源，端侧与契约都不用动**。
- 拼音表是**精选常用字**（不是全字表），未收录的字回退到 `vis_AA`（开口）。
  这是刻意的取舍：仓库只允许 4 个依赖，引拼音库不合适，而全字表体积不划算。
- 不做声调相关的口型差异（普通话声调主要影响音高，对口型影响很小）。

## 用法

    from app.avatar.visemes import build_cues, LIPSYNC_VERSION
    cues = build_cues("妈，今天药按时吃了没")
    # -> {"durationMs": 2340, "cues": [{"c": "妈", "b": 0, "e": 180, "v": [...]}, ...]}
"""

from __future__ import annotations

import re
from typing import Iterable

LIPSYNC_VERSION = 1

# 每个字的默认时长（毫秒）。真 TTS 对齐就绪后这个只作为兜底。
DEFAULT_CHAR_MS = 180
# 句中标点的停顿（毫秒）
PAUSE_COMMA_MS = 220
PAUSE_SENTENCE_MS = 380

# 声母 → viseme（与 3D建模/03_doc/morph-viseme-cosyvoice2.json 的口径一致）
INITIAL_VISEME = {
    "b": "vis_MBP", "p": "vis_MBP", "m": "vis_MBP",
    "f": "vis_FV",
    "d": "vis_L", "t": "vis_L", "n": "vis_NN", "l": "vis_L",
    "g": "vis_KK", "k": "vis_KK", "h": "vis_KK",
    "j": "vis_SS", "q": "vis_SS", "x": "vis_SS",
    "zh": "vis_SS", "ch": "vis_SS", "sh": "vis_SS", "r": "vis_RR",
    "z": "vis_SS", "c": "vis_SS", "s": "vis_SS",
    "y": "vis_I", "w": "vis_WQ",
}

# 韵母 → viseme 序列（复韵母按时序给多个，遵循 JSON 里的 diphthongPolicy）
FINAL_VISEMES = {
    "a": ["vis_AA"], "o": ["vis_O"], "e": ["vis_E"], "i": ["vis_I"], "u": ["vis_U"],
    "v": ["vis_U"], "er": ["vis_RR"],
    "ai": ["vis_AA", "vis_I"], "ei": ["vis_E", "vis_I"],
    "ao": ["vis_AA", "vis_O"], "ou": ["vis_O", "vis_U"],
    "an": ["vis_AA"], "en": ["vis_E"], "ang": ["vis_AA"], "eng": ["vis_E"], "ong": ["vis_O"],
    "ia": ["vis_I", "vis_AA"], "ie": ["vis_I", "vis_E"], "iao": ["vis_I", "vis_AA", "vis_O"],
    "iu": ["vis_I", "vis_U"], "ian": ["vis_I"], "in": ["vis_I"], "iang": ["vis_I"],
    "ing": ["vis_I"], "iong": ["vis_I"],
    "ua": ["vis_U", "vis_AA"], "uo": ["vis_U", "vis_O"], "uai": ["vis_U", "vis_AA", "vis_I"],
    "ui": ["vis_U", "vis_I"], "uan": ["vis_U"], "un": ["vis_U"], "uang": ["vis_U"],
    "ueng": ["vis_U"], "ve": ["vis_U", "vis_E"], "van": ["vis_U"], "vn": ["vis_U"],
}

# 精选常用字 → 无声调拼音（覆盖日常对话里的高频字；未收录回退 DEFAULT_VISEME）
PINYIN = {
    "们": "men", "的": "de", "了": "le", "是": "shi", "在": "zai", "有": "you",
    "妈": "ma", "爸": "ba", "你": "ni", "我": "wo", "他": "ta", "她": "ta", "它": "ta",
    "不": "bu", "和": "he", "就": "jiu", "都": "dou", "也": "ye", "还": "hai",
    "要": "yao", "会": "hui", "能": "neng", "可": "ke", "以": "yi", "好": "hao",
    "很": "hen", "这": "zhe", "那": "na", "个": "ge", "些": "xie", "什么": "shenme",
    "怎": "zen", "么": "me", "样": "yang", "谁": "shui", "哪": "na", "里": "li",
    "吃": "chi", "喝": "he", "睡": "shui", "觉": "jiao", "走": "zou", "来": "lai",
    "去": "qu", "回": "hui", "到": "dao", "看": "kan", "听": "ting", "说": "shuo",
    "做": "zuo", "给": "gei", "拿": "na", "放": "fang", "开": "kai", "关": "guan",
    "今": "jin", "天": "tian", "明": "ming", "昨": "zuo", "早": "zao", "晚": "wan",
    "上": "shang", "下": "xia", "中": "zhong", "午": "wu", "点": "dian", "分": "fen",
    "年": "nian", "月": "yue", "日": "ri", "号": "hao", "星期": "xingqi",
    "药": "yao", "医": "yi", "生": "sheng", "院": "yuan", "病": "bing", "身": "shen",
    "体": "ti", "血": "xue", "压": "ya", "糖": "tang", "心": "xin", "脏": "zang",
    "头": "tou", "疼": "teng", "痛": "tong", "舒": "shu", "服": "fu",
    "饭": "fan", "菜": "cai", "水": "shui", "汤": "tang", "果": "guo", "茶": "cha",
    "子": "zi", "女": "nv", "儿": "er", "孙": "sun", "家": "jia", "人": "ren",
    "老": "lao", "太": "tai", "爷": "ye", "奶": "nai", "姨": "yi", "叔": "shu",
    "朋": "peng", "友": "you", "邻": "lin", "居": "ju",
    "好": "hao", "行": "xing", "对": "dui", "没": "mei", "事": "shi", "别": "bie",
    "请": "qing", "谢": "xie", "再": "zai", "见": "jian", "您": "nin",
    "一": "yi", "二": "er", "三": "san", "四": "si", "五": "wu", "六": "liu",
    "七": "qi", "八": "ba", "九": "jiu", "十": "shi", "百": "bai", "千": "qian",
    "坐": "zuo", "站": "zhan", "起": "qi", "躺": "tang", "慢": "man", "快": "kuai",
    "多": "duo", "少": "shao", "大": "da", "小": "xiao", "高": "gao", "低": "di",
    "冷": "leng", "热": "re", "暖": "nuan", "凉": "liang", "风": "feng", "雨": "yu",
    "雪": "xue", "晴": "qing", "阴": "yin", "天": "tian",
    "记": "ji", "得": "de", "忘": "wang", "想": "xiang", "念": "nian", "喜": "xi",
    "欢": "huan", "爱": "ai", "怕": "pa", "累": "lei", "忙": "mang", "闲": "xian",
    "帮": "bang", "忙": "mang", "等": "deng", "着": "zhe", "先": "xian", "后": "hou",
    "现": "xian", "在": "zai", "已": "yi", "经": "jing", "刚": "gang", "才": "cai",
    "正": "zheng", "在": "zai", "马": "ma", "上": "shang",
    "很": "hen", "挺": "ting", "真": "zhen", "太": "tai", "特": "te", "别": "bie",
    "问": "wen", "题": "ti", "办": "ban", "法": "fa", "需": "xu", "要": "yao",
    "准": "zhun", "备": "bei", "完": "wan", "成": "cheng", "始": "shi",
    "电": "dian", "话": "hua", "视": "shi", "频": "pin", "聊": "liao", "通": "tong",
    "视": "shi", "频": "pin", "照": "zhao", "片": "pian",
}

# 未收录字的回退：开口（比回退到 silence 更像"在说话"）
DEFAULT_VISEME = "vis_AA"
SILENCE = "vis_silence"

# 标点：句中标点给短停顿，句末标点给长停顿
_SOFT_PUNCT = "，,、；;：:"
_HARD_PUNCT = "。！？!?…"
_CJK = re.compile(r"[\u4e00-\u9fff]")
_LATIN = re.compile(r"[A-Za-z]")


def _split_syllable(syllable: str) -> tuple[str, str]:
    """把无声调拼音切成（声母, 韵母）。声母最长 2 个字母（zh/ch/sh）。"""
    two = syllable[:2]
    if two in INITIAL_VISEME:
        return two, syllable[2:]
    one = syllable[:1]
    if one in INITIAL_VISEME:
        return one, syllable[1:]
    return "", syllable


def visemes_for_char(ch: str) -> list[str]:
    """单个汉字 → viseme 序列（含声母与韵母，最多 2 个）。

    最多 2 个是刻意的：`morph-viseme-cosyvoice2.json` 的 `timingHint` 写明
    "同一时刻最多混 2 个 viseme，权重和 <= 1"，后端先收敛，端侧就不必再裁。
    """
    syllable = PINYIN.get(ch)
    if not syllable:
        return [DEFAULT_VISEME]
    initial, final = _split_syllable(syllable)
    out: list[str] = []
    if initial:
        out.append(INITIAL_VISEME[initial])
    finals = FINAL_VISEMES.get(final) or FINAL_VISEMES.get(final[:2]) or [DEFAULT_VISEME]
    out.extend(finals)
    # 去重（如 vis_L + vis_L）并压到 2 个
    deduped: list[str] = []
    for item in out:
        if not deduped or deduped[-1] != item:
            deduped.append(item)
    return deduped[:2]


def build_cues(text: str, char_ms: int = DEFAULT_CHAR_MS) -> dict:
    """把一段文字编成口型关键帧。

    返回 `{"durationMs": int, "cues": [{"c", "b", "e", "v": [...]}, ...]}`。
    空白与标点不产生可见口型（标点只产生停顿），避免"嘴在标点处乱动"。

    ⚠️ 时间轴按字数估算，**不是真实语音对齐**——见模块顶部"诚实边界"。
    """
    cues: list[dict] = []
    cursor = 0
    for ch in text or "":
        if ch.isspace():
            cursor += 40
            continue
        if ch in _HARD_PUNCT:
            cursor += PAUSE_SENTENCE_MS
            continue
        if ch in _SOFT_PUNCT:
            cursor += PAUSE_COMMA_MS
            continue
        if _CJK.match(ch):
            visemes = visemes_for_char(ch)
        elif _LATIN.match(ch):
            visemes = ["vis_I"] if ch.lower() in "iye" else [DEFAULT_VISEME]
        else:
            # 数字、符号等：给一个轻量的开口，不要留成沉默（否则嘴会"跳过"这些字）
            visemes = [DEFAULT_VISEME]
        start = cursor
        cursor += char_ms
        cues.append({"c": ch, "b": start, "e": cursor, "v": visemes})
    # 收尾：加一小段沉默，让嘴回到静止（否则最后一句的口型会"挂"在脸上）
    if cursor > 0:
        cues.append({"c": "", "b": cursor, "e": cursor + 120, "v": [SILENCE]})
    return {"durationMs": cursor + 120, "cues": cues}


def build_lipsync_payload(text: str, assistant_msg_id: str, char_ms: int = DEFAULT_CHAR_MS) -> dict:
    """成 SSE `lipsync` 事件的 payload（字段名以 `uni-app/api/README.md` 为准）。"""
    built = build_cues(text, char_ms=char_ms)
    return {
        "assistantMsgId": assistant_msg_id,
        "durationMs": built["durationMs"],
        "cues": built["cues"],
        "version": LIPSYNC_VERSION,
        "source": "estimated",   # estimated | tts-aligned —— 端侧据此判断要不要做额外平滑
    }


def iter_visemes(text: str) -> Iterable[str]:
    """遍历这段文字会用到的 viseme（调试/校验用）。"""
    for ch in text or "":
        if _CJK.match(ch):
            for item in visemes_for_char(ch):
                yield item
