"""
比邻AI · wiki 更新（从对话里学）

## 这是"越聊越像人"的核心

每轮对话结束后，让模型看一遍"老人说了什么 / 子女怎么回的"，
把**值得长期记住的东西**合进两份 wiki：

  · 老人画像：他今天说了什么新情况（身体、家里的事、爱吃什么、最近干嘛）
  · 子女风格：他怎么说话（口头禅、称呼、语气、关心方式）

## 四个必须守住的约束

**1. 只记事实，不记猜测**
   "我妈腿疼" 是事实；"我妈可能有关节炎" 是推断，不能进 wiki。
   推断一旦进 wiki，下一轮会被当事实再喂回去，越滚越离谱。

**2. 合并而不是追加**
   同一节里"爱听戏"出现五次，只留一条。否则聊三个月会自动生成一屏重复。

**3. 不能覆盖子女手填的内容**
   子女在「智能体角色」里填的称呼、关系是权威的。
   wiki 学到的东西不能把它改掉 —— 用户填的东西比他猜的准。

**4. 更新失败绝不影响对话**
   这是增强功能。任何异常都只记日志，不能让老人的消息发不出去。

## 为什么不在请求链路里同步更新

更新要额外调一次模型（几百毫秒到几秒）。放在老人的请求里会让他等回复变慢。
所以**异步**：回复发完之后再跑，失败也不重试（下一轮还会学到）。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from .models import (
    ELDER_SECTIONS,
    MAX_ITEMS_PER_SECTION,
    PERSISTENT_SECTIONS,
    PERSONA_SECTIONS,
    WIKI_ELDER,
    WIKI_PERSONA,
    WikiItem,
    WikiPage,
    WikiSection,
)

logger = logging.getLogger("bilin.wiki")

#: 家人会话专用：要同时归属两方
#:
#: 为什么需要单独一套提示词：
#:   需求「老人跟子女聊就同时记录老人和子女的表达习惯」。
#:   但服务端的 senderRole 只区分"人 / 智能体"，**分不出是哪个家人**
#:   （见 messaging/models.py）。所以只能让模型按**内容**归属：
#:   "妈 我今儿加班" 是子女，"我血压高" 是老人 —— 上下文足够判断。
#:   判错了用户能在「AI 了解我的」页面上删，代价可控。

EXTRACT_PROMPT = """你从一段对话里，整理出**值得长期记住**的事实。

## 只记这些

**老人画像**（关于这位老人本人）：
- 基本情况：姓名、年龄、住哪儿、退休前做什么
- 家庭：老伴、子女、孙辈，谁常来看他
- 身体状况：确诊的病、常吃的药、听力视力腿脚的限制
- 生活习惯：作息、每天固定做的事
- 饮食口味：爱吃什么、不吃什么、忌口
- 兴趣爱好：爱听戏、爱下棋、爱看什么节目
- 说话习惯：**他本人**的口头禅、语气、爱用的词、说话长短
- 近况：最近发生的事、家里的大事
- 聊过的话题：聊过的具体事，避免反复问
- 敏感点：不爱提的人或事

**子女说话风格**（关于"跟他说话的人"怎么说话）：
- 口头禅：他爱说的短句、语气词
- 称呼习惯：怎么叫老人
- 说话风格：话多话少、爱不爱开玩笑、语气急不急
- 常用表达：固定说法、方言词
- 关心方式：他表达关心的习惯
- 禁忌话题：不愿聊的
- 情绪触发：什么话题会特别高兴或沉默

## 绝对不要记

- **推测和判断**（"可能有高血压"）—— 只记他**明说**的事实
- 一次性的闲聊（"今天天气不错""我刚吃完饭"）
- 你自己的回答内容
- 已经被别的条目涵盖的内容
- 没有新信息的话（"嗯""好""知道了"）

## 输出格式

只输出 JSON，不要解释。没有可记的就输出 `{"elder":{},"persona":{}}`。

```json
{
  "elder": {"身体状况": ["高血压，每天吃氨氯地平"], "饮食口味": ["不爱吃甜的"]},
  "persona": {"称呼习惯": ["叫老人「妈」"], "口头禅": ["吃了没"]}
}
```

key 只能从上面列的小节名里选，value 是简短的句子（12 字以内最好）。
每条必须是**独立可读的事实**，不要写"他说""提到"这种转述前缀。"""
EXTRACT_PROMPT_FAMILY = EXTRACT_PROMPT + """

## 这一轮是「老人和家人」的聊天（不是和智能体）

所以要在**同一段对话里分清楚谁是谁**，把内容归到正确的一侧：

- **老人说的是**：关于他自己的身体、吃了什么、家里的事、心情的句子
  → 归到「老人画像」的相应小节
  老人说话的方式（口头禅、语气、爱用的词）→ 归到「说话习惯」
- **家人说的是**：关心他、跟他说自己的事、叮嘱他的句子
  → 家人说话的方式（口头禅、称呼、语气、关心方式）→ 归到「子女说话风格」

判据举例：
  · "妈 我今儿加班 你先吃"    → 家人（叫"妈"、说自己加班）
  · "我血压高 天天吃药"        → 老人（说自己身体）
  · "你记得量血压啊"           → 家人（叮嘱）
  · "我量了 138"               → 老人（报数字）

分不清就**两边都不记**，不要硬塞。
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _norm(text: str) -> str:
    """归一化用于判重：去空白与标点。"""
    out = []
    for ch in str(text or ""):
        if ch.isalnum() or "\u4e00" <= ch <= "\u9fff":
            out.append(ch.lower())
    return "".join(out)


#: 判定"说的是同一件事"的字符重合阈值。
#:
#: ⚠️ 这个值调过：最初用 0.66，结果**过度合并** ——
#:    "叫老人妈" 与 "叫老人爸"（重合 3/4=0.75）
#:    "不爱吃甜的" 与 "不爱吃辣"（重合 3/4=0.75）
#:    都被判成同一条，后者直接丢失。**信息丢了比留两条重复更糟**。
#:
#: 现在的取舍：只合并"几乎一模一样"的，宁可留两条相近的。
#:   真正的重复（同一句话说五遍）由"归一化后完全相等"兜住，不依赖这个阈值。
SIMILAR_RATIO = 0.85


def _too_similar(existing: list[str], candidate: str) -> bool:
    """候选是否已存在。

    三级判定，命中任一即算重复：
      1. 归一化后**完全相等**（去空白标点）—— 这是主力，重复句全靠它
      2. **子串包含**（"爱听戏" ⊂ "爱听传统戏"；"高血压" ⊂ "高血压，每天吃氨氯地平"）
      3. 字符重合率 ≥ SIMILAR_RATIO —— 只兜"几乎一字不差"的情况

    ⚠️ 阈值宁可**保守**：漏合并只是多一条相近记录，过度合并会**直接丢信息**。
       这条判断是实测调出来的（0.66 会把"叫老人妈/叫老人爸"合成一条）。
    """
    key = _norm(candidate)
    if not key:
        return True
    chars = set(key)
    for old in existing:
        old_key = _norm(old)
        if not old_key:
            continue
        if key == old_key or key in old_key or old_key in key:
            return True
        old_chars = set(old_key)
        overlap = len(chars & old_chars)
        if overlap and overlap / min(len(chars), len(old_chars)) >= SIMILAR_RATIO:
            return True
    return False


def _parse_json(raw: str) -> dict:
    """从模型输出里抠出 JSON（模型偶尔会包一层 ```json）。"""
    text = str(raw or "").strip()
    if not text:
        return {}
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        data = json.loads(text[start:end + 1])
    except (ValueError, TypeError):
        logger.info("wiki 提取结果不是合法 JSON，本轮跳过")
        return {}
    return data if isinstance(data, dict) else {}


def merge_facts(page: WikiPage, facts: dict, *, frequent: tuple[str, ...] = ()) -> int:
    """把提取到的事实合并进 wiki，返回新增条数。

    `frequent`：这一批对话里**反复出现**的短语（来自 app/history/frequency.py）。
    带这个是为了实现需求里"优先保留出现次数多的"：
    高频内容即使模型没抽出来，也会作为条目补进去。

    合并规则：
      · 只接受**已定义的小节**（防止 LLM 造新标题）
      · 已存在相似的条目 → **移到末尾**而不是跳过（等价于刷新，避免被裁掉）
      · 每节封顶 MAX_ITEMS_PER_SECTION，超了丢**最旧**的
      · `口头禅` / `称呼习惯` 是长期记忆，**不裁剪**（见 PERSISTENT_SECTIONS）
    """
    if not isinstance(facts, dict):
        facts = {}
    allowed = {title for title, _hint in (ELDER_SECTIONS if page.kind == WIKI_ELDER else PERSONA_SECTIONS)}
    moment = _now_iso()
    added = 0

    for title, values in facts.items():
        name = str(title or "").strip()
        if name not in allowed:
            continue
        section = page.sections.get(name)
        if section is None:
            continue
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            continue

        for value in values:
            text = str(value or "").strip()
            # 太短的多半是"嗯""好"，没有信息量
            if len(text) < 2:
                continue
            # 过长的多半是模型在写作文，截一下防止单条吞掉整节预算
            if len(text) > 60:
                text = text[:60]

            hit = _similar_item(section.items, text)
            if hit is not None:
                # 又提到了同一件事：把它移到末尾（刷新），这样裁剪时不会被丢掉。
                # 这就是"优先保留出现次数多的"在条目层面的落地。
                section.items.remove(hit)
                section.items.append(hit)
                continue

            section.items.append(WikiItem(text=text, source="chat", updated_at=moment))
            added += 1

        _trim(section, name)

    if added:
        page.updated_at = moment
    return added


def _trim(section: WikiSection, title: str) -> None:
    """超上限时丢最旧的；长期记忆小节不裁。"""
    if title in PERSISTENT_SECTIONS:
        return
    if len(section.items) > MAX_ITEMS_PER_SECTION:
        section.items = section.items[-MAX_ITEMS_PER_SECTION:]


def _similar_item(items: list[WikiItem], candidate: str) -> WikiItem | None:
    """找出与候选重复的已有条目（没有就 None）。"""
    for item in items:
        if _too_similar([item.text], candidate):
            return item
    return None


def build_update_messages(
    turns: list[tuple[str, str]],
    elder_page: WikiPage,
    persona_page: WikiPage,
    *,
    family: bool = False,
) -> list[dict]:
    """拼"提取事实"这次调用的消息。

    `turns` 是**多轮**对话（[(老人说的, 对方回的), ...]）。

    `family=True` 时用家人会话那套提示词（要在一段对话里分清谁是谁，
    见 EXTRACT_PROMPT_FAMILY）。为什么分两套：
      智能体会话里"对方"就是 AI 自己，只需抽老人侧；
      家人会话里两边都是真人，要同时记录老人和子女的表达习惯（需求原话）。

    为什么支持多轮：学习从"每轮一次"改成"每 N 轮一次"，
    如果只拿第 N 轮去学，前面 N-1 轮的内容就白丢了。
    这里把攒下来的几轮一起给模型，效果不比逐轮差，调用次数却降到 1/N。

    把**已有的 wiki 内容**也带上：模型能据此避免重复记录，
    而不是每次重新发现一次"他叫老人妈"。
    """
    def render(page: WikiPage) -> str:
        parts: list[str] = []
        for title, section in page.sections.items():
            if section.is_empty():
                continue
            parts.append(f"【{title}】" + "；".join(item.text for item in section.items))
        return "\n".join(parts) if parts else "（还没有记录）"

    transcript: list[str] = []
    for elder_text, agent_text in turns:
        if elder_text:
            transcript.append(f"老人说：{elder_text}")
        if agent_text:
            transcript.append(f"对方回：{agent_text}")
    dialogue = "\n".join(transcript) if transcript else "（这段没有内容）"

    user_block = (
        "## 已经记下的（不要重复记）\n"
        f"### 老人画像\n{render(elder_page)}\n\n"
        f"### 子女说话风格\n{render(persona_page)}\n\n"
        f"## 这一段新对话（{len(turns)} 轮）\n"
        f"{dialogue}\n\n"
        "请按规则输出 JSON。没有值得记的就输出 {\"elder\":{},\"persona\":{}}。"
    )
    return [
        {"role": "system", "content": EXTRACT_PROMPT_FAMILY if family else EXTRACT_PROMPT},
        {"role": "user", "content": user_block},
    ]
