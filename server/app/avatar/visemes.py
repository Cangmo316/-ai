"""比邻AI · 文字/对齐 → 口型关键帧（viseme cues）

## 这一层干什么

把一句话变成**带时间区间的口型指令**，端侧只做插值并把权重写进形态键
（`face-three.js` 的 `setVisemes`）。契约见 `uni-app/api/README.md` 的 SSE `lipsync` 事件。

有两条产出路径，**共用同一个契约**：

| 路径 | 何时用 | `source` 字段 |
|---|---|---|
| `build_lipsync_payload(text)` | 还没有音频（当前状态）——按字数**估算**时间轴 | `estimated` |
| `from_alignment(segments)` | 有了真语音（CosyVoice 2 + WhisperX/MFA 强制对齐）——用**真时间戳** | `tts-aligned` |

选型文档（`比邻AI_医学条目与语音技术选型.md` §2.1 L113-114）定的就是后者这条管线；
前者是为了"音频链路还没做出来时先让口型能动"。

## 为什么"字 → viseme"放在后端

`uni-app/` 工程是**零 npm 依赖**，端侧没有拼音表（全仓 grep `pinyin` 为 0 命中）；
把汉字解析放后端，端侧就只需要"按时间插值"这一件小事，逻辑最少、出错面最小。

## ⚠️ 当前实现的诚实边界

- `build_lipsync_payload` 的时间轴是**按字数等分估算**的，不是真实语音对齐。
- 拼音表是**精选常用字**（不是全字表），未收录的字回退 `vis_AA`（开口）。
  这是刻意取舍：仓库只允许 4 个依赖，引拼音库不合适，全字表体积也不划算。
- 不做声调相关的口型差异（声调主要影响音高，对口型影响很小）。
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
    "妈": "ma", "爸": "ba", "你": "ni", "我": "wo", "他": "ta", "她": "ta", "它": "ta",
    "们": "men", "的": "de", "了": "le", "是": "shi", "在": "zai", "有": "you",
    "不": "bu", "和": "he", "就": "jiu", "都": "dou", "也": "ye", "还": "hai",
    "要": "yao", "会": "hui", "能": "neng", "可": "ke", "以": "yi", "好": "hao",
    "很": "hen", "这": "zhe", "那": "na", "个": "ge", "些": "xie",
    "怎": "zen", "么": "me", "样": "yang", "谁": "shui", "哪": "na", "里": "li",
    "吃": "chi", "喝": "he", "睡": "shui", "觉": "jiao", "走": "zou", "来": "lai",
    "去": "qu", "回": "hui", "到": "dao", "看": "kan", "听": "ting", "说": "shuo",
    "做": "zuo", "给": "gei", "拿": "na", "放": "fang", "开": "kai", "关": "guan",
    "今": "jin", "天": "tian", "明": "ming", "昨": "zuo", "早": "zao", "晚": "wan",
    "上": "shang", "下": "xia", "中": "zhong", "午": "wu", "点": "dian", "分": "fen",
    "年": "nian", "月": "yue", "日": "ri", "号": "hao", "星": "xing", "期": "qi",
    "药": "yao", "医": "yi", "生": "sheng", "院": "yuan", "病": "bing", "身": "shen",
    "体": "ti", "血": "xue", "压": "ya", "糖": "tang", "心": "xin", "脏": "zang",
    "头": "tou", "疼": "teng", "痛": "tong", "舒": "shu", "服": "fu",
    "饭": "fan", "菜": "cai", "水": "shui", "汤": "tang", "果": "guo", "茶": "cha",
    "子": "zi", "女": "nv", "儿": "er", "孙": "sun", "家": "jia", "人": "ren",
    "老": "lao", "太": "tai", "爷": "ye", "奶": "nai", "姨": "yi", "叔": "shu",
    "朋": "peng", "友": "you", "邻": "lin", "居": "ju",
    "行": "xing", "对": "dui", "没": "mei", "事": "shi", "别": "bie",
    "请": "qing", "谢": "xie", "再": "zai", "见": "jian", "您": "nin",
    "一": "yi", "二": "er", "三": "san", "四": "si", "五": "wu", "六": "liu",
    "七": "qi", "八": "ba", "九": "jiu", "十": "shi", "百": "bai", "千": "qian",
    "坐": "zuo", "站": "zhan", "起": "qi", "躺": "tang", "慢": "man", "快": "kuai",
    "多": "duo", "少": "shao", "大": "da", "小": "xiao", "高": "gao", "低": "di",
    "冷": "leng", "热": "re", "暖": "nuan", "凉": "liang", "风": "feng", "雨": "yu",
    "雪": "xue", "晴": "qing", "阴": "yin",
    "记": "ji", "得": "de", "忘": "wang", "想": "xiang", "念": "nian", "喜": "xi",
    "欢": "huan", "爱": "ai", "怕": "pa", "累": "lei", "忙": "mang", "闲": "xian",
    "帮": "bang", "等": "deng", "着": "zhe", "先": "xian", "后": "hou",
    "现": "xian", "已": "yi", "经": "jing", "刚": "gang", "才": "cai",
    "正": "zheng", "马": "ma",
    "挺": "ting", "真": "zhen", "特": "te",
    "问": "wen", "题": "ti", "办": "ban", "法": "fa", "需": "xu",
    "准": "zhun", "备": "bei", "完": "wan", "成": "cheng", "始": "shi",
    "电": "dian", "话": "hua", "视": "shi", "频": "pin", "聊": "liao", "通": "tong",
    "照": "zhao", "片": "pian",
}

# 未收录字的回退：开口（比回退到 silence 更像"在说话"）
DEFAULT_VISEME = "vis_AA"
SILENCE = "vis_silence"

# 标点：句中标点给短停顿，句末标点给长停顿
_SOFT_PUNCT = "，,、；;：:"
_HARD_PUNCT = "。！？!?…"
_CJK = re.compile(r"[\u4e00-\u9fff]")
_LATIN = re.compile(r"[A-Za-z]")

# 对齐工具给的时间：大于这个数就认为是**毫秒**（一段回复不可能有 10 万秒）
_ALIGN_SECONDS_THRESHOLD = 1e5


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
    deduped: list[str] = []
    for item in out:
        if not deduped or deduped[-1] != item:
            deduped.append(item)
    return deduped[:2]


def _visemes_for_token(token: str) -> list[str]:
    """非汉字 token 的口型（拉丁字母 / 数字 / 符号）。"""
    if _CJK.match(token):
        return visemes_for_char(token)
    if _LATIN.match(token):
        return ["vis_I"] if token.lower() in "iye" else [DEFAULT_VISEME]
    return [DEFAULT_VISEME]


def build_cues(text: str, char_ms: int = DEFAULT_CHAR_MS) -> dict:
    """把一段文字编成口型关键帧（**时间轴按字数估算**）。

    返回 `{"durationMs": int, "cues": [{"c", "b", "e", "v": [...]}, ...]}`。
    空白与标点不产生可见口型（标点只产生停顿），避免"嘴在标点处乱动"。
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
        start = cursor
        cursor += char_ms
        cues.append({"c": ch, "b": start, "e": cursor, "v": _visemes_for_token(ch)})
    if cursor > 0:
        cues.append({"c": "", "b": cursor, "e": cursor + 120, "v": [SILENCE]})
    return {"durationMs": cursor + 120, "cues": cues}


def build_lipsync_payload(text: str, assistant_msg_id: str, char_ms: int = DEFAULT_CHAR_MS) -> dict:
    """估算版 payload（还没有音频时用；`source: "estimated"`）。"""
    built = build_cues(text, char_ms=char_ms)
    return {
        "assistantMsgId": assistant_msg_id,
        "durationMs": built["durationMs"],
        "cues": built["cues"],
        "version": LIPSYNC_VERSION,
        "source": "estimated",
    }


def _to_millis(value, assume_millis: bool) -> float:
    """把对齐工具给的时间换算成毫秒。

    `assume_millis=True` 表示"**已经是毫秒**，直接用"；
    否则按**秒**处理、×1000。单位由调用方按**整批**判定（`_infer_millis`），
    不能逐条判——单条短片段（如 `end=400`）逐条判会判错。
    """
    number = float(value)
    return number if assume_millis else number * 1000.0


def _infer_millis(max_time: float) -> bool:
    """整批时间戳是"毫秒"吗？——返回 True 表示**已经是毫秒**（不必 ×1000）。

    ## 判据（只看整段的**最大时间戳**，不能逐条判）

    两种单位下，**单句**的数值区间几乎不重叠：

    | 单位 | 单句数值范围 | 说明 |
    |---|---|---|
    | 秒（WhisperX / MFA） | 0.5 ~ 60 | 真人一句 0.5~60 秒；>60 秒的单句不存在 |
    | 毫秒 | 200 ~ 60000 | 最短的单字约 180ms，整句必有几百 ms |

    所以取 **200** 作分界：`>= 200` 判为毫秒，`< 200` 判为秒。
    （第一版取 1000 做分界，把 `end=400` 判成了"400 秒" → 时长算成 400,120ms；测试抓住了。）

    ## 返回值方向（也写错过）

    `_to_millis(value, assume_millis)` 在 `assume_millis=False` 时**按秒 ×1000**，
    所以本函数必须返回"**是否已经是毫秒**"。
    """
    return max_time >= 200


def from_alignment(segments: Iterable[dict], assistant_msg_id: str,
                   duration_ms: float | None = None) -> dict:
    """把**强制对齐**（WhisperX / MFA）的结果转成 `lipsync` payload。

    接受 WhisperX 形状的输入（每项至少 `word`/`start`/`end`，单位秒）::

        [{"word": "妈", "start": 0.00, "end": 0.18},
         {"word": "，", "start": 0.18, "end": 0.18},
         {"word": "今", "start": 0.40, "end": 0.58}, ...]

    处理三件容易踩的事：
    1. **时间单位**：自动识别秒/毫秒（见 `_ALIGN_SECONDS_THRESHOLD`）。
    2. **标点与空白**：不产生口型，只推进时间轴（与估算版口径一致）。
    3. **异常区间**：`end <= start`（WhisperX 对标点常给 0 长度）→ 给一个最小可见时长，
       否则那个字的口型会被"吞掉"、嘴看起来漏字。
    4. **一个词多个字**：WhisperX 常按词给时间，这里在词内**逐字均分**该时间段。

    对齐质量差时不要在这里硬撑：本函数只保证**结构正确**，
    "准不准"由调用方按 `source` 字段决定是否回退到估算版。
    """
    cues: list[dict] = []
    cursor = 0.0
    # 单位**整批判定**（逐条判会把短音频的毫秒值误判成秒，见 _to_millis 的说明）
    raw = [segment for segment in (segments or []) if isinstance(segment, dict)]
    max_time = 0.0
    for segment in raw:
        for key in ("start", "end"):
            try:
                max_time = max(max_time, float(segment.get(key, 0) or 0))
            except (TypeError, ValueError):
                continue
    assume_millis = _infer_millis(max_time)

    for segment in raw:
        if not isinstance(segment, dict):
            continue
        word = str(segment.get("word") or segment.get("text") or "")
        if not word or "start" not in segment or "end" not in segment:
            continue
        try:
            start = _to_millis(segment["start"], assume_millis)
            end = _to_millis(segment["end"], assume_millis)
        except (TypeError, ValueError):
            continue
        visible = word.strip()
        if not visible or all(ch in _SOFT_PUNCT + _HARD_PUNCT + " " for ch in visible):
            cursor = max(cursor, end)
            continue
        if end <= start:
            end = start + DEFAULT_CHAR_MS
        start = max(start, cursor)
        end = max(end, start + 1)
        chars = list(visible)
        span = (end - start) / max(len(chars), 1)
        for index, ch in enumerate(chars):
            char_start = start + span * index
            cues.append({
                "c": ch,
                "b": round(char_start),
                "e": round(char_start + span),
                "v": _visemes_for_token(ch),
            })
        cursor = end

    total = duration_ms if isinstance(duration_ms, (int, float)) and duration_ms > 0 else cursor
    if cues:
        cues.append({"c": "", "b": round(total), "e": round(total + 120), "v": [SILENCE]})
        total = total + 120
    return {
        "assistantMsgId": assistant_msg_id,
        "durationMs": round(total),
        "cues": cues,
        "version": LIPSYNC_VERSION,
        # 端侧据此知道"这是真语音对齐的"，可以完全信任、不必再平滑
        "source": "tts-aligned",
    }


def iter_visemes(text: str) -> Iterable[str]:
    """遍历这段文字会用到的 viseme（调试/校验用）。"""
    for ch in text or "":
        if _CJK.match(ch):
            for item in visemes_for_char(ch):
                yield item
