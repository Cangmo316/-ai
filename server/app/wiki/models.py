"""
比邻AI · LLM wiki（替代关键词记忆检索）

## 为什么要换掉原来的做法

原来的记忆检索是**关键词打分**：把老人的话切成中文字符，跟存储的记忆条目
做字符重合度打分，取前几条注进 prompt。它有三个绕不过去的问题：

1. **记的是碎片**："2023 年儿子带我去过海南" 是一条孤立记录，
   下次聊到"海南"才会被捞出来；没提到的就永远沉默。
2. **不会自己长**：只存"事件"，不存"这个人是什么样"。
   聊了 100 轮，它对老人的理解仍然是 100 条互不相干的碎片。
3. **没有风格**：它知道老人"爱听戏"，但不知道子女平时怎么跟他说话。

## 换成 wiki 之后

每个老人两份 Markdown 文档，由 LLM 在对话过程中**自己维护**：

```
wiki/<elder_id>/elder.md     老人画像：基本情况、家庭、身体、习惯、口味、
                             兴趣、近况、聊过的话题、敏感点
wiki/<elder_id>/persona.md   子女说话风格：口头禅、称呼、语气、句式、
                             常用比喻、禁忌话题、情绪触发点
```

为什么是 Markdown：
  · **人也能读、也能手工改** —— 子女想纠正"我妈不爱吃甜"直接编辑文件即可
  · 分节（`## 标题`）便于**按话题选择性注入**，不用整篇塞进 prompt
  · 出问题能直接看文件排查，不用查数据库

## 三个刻意的设计约束

1. **注入按节挑，不整篇塞**：wiki 会长到几千字，整篇塞会淹掉上下文
   （这也是原来碎片检索的初衷，保留其合理部分）。
2. **更新是"合并"不是"追加"**：同一节的同一件事只留最新最具体的那条，
   否则聊三个月会堆出几十条重复的"爱听戏"。
3. **写失败绝不影响对话**：wiki 是增强，不是主链路。
   任何异常都只记日志，不能让老人这条消息发不出去。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ── 两份 wiki ──────────────────────────────────────────────────────
WIKI_ELDER = "elder"      # 老人画像
WIKI_PERSONA = "persona"  # 子女说话风格

WIKIS = (WIKI_ELDER, WIKI_PERSONA)

WIKI_LABELS = {
    WIKI_ELDER: "老人画像",
    WIKI_PERSONA: "子女说话风格",
}

# ── 分节：写死标题，避免 LLM 每轮自创新标题把文档搞乱 ──────────────
# 顺序即文件中的出现顺序（也是插入 prompt 时的顺序）。
ELDER_SECTIONS: tuple[tuple[str, str], ...] = (
    ("基本情况", "姓名、年龄、住哪儿、退休前做什么"),
    ("家庭", "老伴、子女、孙辈，谁常来看他"),
    ("身体状况", "确诊的病、常年吃的药、身体上的限制（听力/视力/腿脚）"),
    ("生活习惯", "作息、爱做什么、每天固定的事"),
    ("饮食口味", "爱吃什么、不吃什么、忌口"),
    ("兴趣爱好", "爱听戏、爱下棋、爱看什么节目"),
    # 需求：「老人跟ai聊就学习老人表达习惯」——
    # 这是他**本人**怎么说话，与 persona.md（子女怎么说话）是两回事。
    # 有了它，AI 才能在语气上贴近他（他爱说"慢慢来"，AI 就别说"您抓紧"）。
    ("说话习惯", "他的口头禅、语气、爱用的词、说话长短"),
    ("近况", "最近发生的事、家里的大事、心情变化"),
    ("聊过的话题", "聊过的具体话题，避免反复问同一件事"),
    ("敏感点", "不爱提的事、提起会难受的人或话题"),
)

PERSONA_SECTIONS: tuple[tuple[str, str], ...] = (
    ("口头禅", "他平时爱说的短句、习惯性语气词"),
    ("称呼习惯", "怎么叫老人（妈/爸/奶奶…），有没有特别的叫法"),
    ("说话风格", "话多还是话少、爱不爱开玩笑、语气急不急"),
    ("常用表达", "他的固定说法、方言词、比喻方式"),
    ("关心方式", "他表达关心的习惯（叮嘱吃药、问吃了没、直接给钱…）"),
    ("禁忌话题", "他不愿意聊的、一提就回避的"),
    ("情绪触发", "什么话题他会特别高兴 / 特别沉默"),
)

SECTIONS_OF = {
    WIKI_ELDER: ELDER_SECTIONS,
    WIKI_PERSONA: PERSONA_SECTIONS,
}

#: 每节最多保留多少条。不加限制的话 wiki 会无限膨胀，
#: 最后既注入不下、人也没法读。
MAX_ITEMS_PER_SECTION = 12

#: **永久保留**的小节：不做"满了丢最旧"的裁剪。
#:
#: 为什么只有这两节：
#:   · 口头禅 —— 需求原话"有些口头禅需要保留，作为长期记忆"。
#:     它是长期稳定的特征，不该因为近期话题变多就被挤掉。
#:   · 称呼习惯 —— 一旦学到他怎么叫老人，这个事实几乎不会变（除非改口）。
#: 其余小节（近况、饮食口味…）会随人变化，按最近优先裁剪是合理的。
#:
#: "人也是会变的"这条需求的落地方式：
#:   · 易变的小节 → 满了丢最旧（近期优先）
#:   · 稳定的小节 → 永久保留（这条）
#:   · 反复被提到的条目 → 合并时会移到末尾（等价于"刷新"，不会被裁掉）
PERSISTENT_SECTIONS = ("口头禅", "称呼习惯")

#: 整份 wiki 注入 prompt 的字符上限。
#: 超了就按"小节优先 + 条目优先"截断（见 inject.py）。
MAX_INJECT_CHARS = 1800


@dataclass
class WikiItem:
    """一条事实。"""

    text: str
    #: 来源：family=子女填的 / chat=聊天里学的 / manual=人工编辑
    source: str = "chat"
    #: 最近一次被提到的时间（ISO），用于"是否新鲜"的排序
    updated_at: str = ""

    def to_line(self) -> str:
        return self.text


@dataclass
class WikiSection:
    """一个分节（对应 Markdown 里的 `## 标题`）。"""

    title: str
    hint: str = ""
    items: list[WikiItem] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.items

    def render(self) -> str:
        """渲染成 Markdown（含标题与说明注释）。"""
        lines = [f"## {self.title}"]
        for item in self.items:
            lines.append(f"- {item.text}")
        return "\n".join(lines)


@dataclass
class WikiPage:
    """一份 wiki 文档。"""

    kind: str
    elder_id: str
    sections: dict[str, WikiSection] = field(default_factory=dict)
    updated_at: str = ""

    @staticmethod
    def empty(kind: str, elder_id: str) -> "WikiPage":
        page = WikiPage(kind=kind, elder_id=elder_id)
        for title, hint in SECTIONS_OF.get(kind, ()):
            page.sections[title] = WikiSection(title=title, hint=hint)
        return page

    @property
    def label(self) -> str:
        return WIKI_LABELS.get(self.kind, self.kind)

    def is_empty(self) -> bool:
        return all(section.is_empty() for section in self.sections.values())

    def total_items(self) -> int:
        return sum(len(section.items) for section in self.sections.values())

    def to_markdown(self) -> str:
        """渲染成 Markdown 全文（带文件头说明，方便人工编辑）。"""
        head = [
            f"# {self.label}",
            "",
            f"<!-- 老人 ID: {self.elder_id} · 由 AI 在对话中自动维护 · 也可以直接手工修改 -->",
            f"<!-- 最后更新: {self.updated_at or '（还没更新过）'} -->",
            "",
            "<!-- 编辑约定：每节用 `## 标题` 开头，条目用 `- ` 开头。",
            "     改条目文字、删条目都安全；不要改标题（程序按标题分节）。 -->",
            "",
        ]
        body: list[str] = []
        for title, _hint in SECTIONS_OF.get(self.kind, ()):
            section = self.sections.get(title)
            if section is None:
                section = WikiSection(title=title)
                self.sections[title] = section
            body.append(section.render())
            body.append("")
        return "\n".join(head) + "\n".join(body)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "label": self.label,
            "elderId": self.elder_id,
            "updatedAt": self.updated_at,
            "sections": [
                {
                    "title": section.title,
                    "items": [item.text for item in section.items],
                }
                for section in self.sections.values()
                if not section.is_empty()
            ],
        }


def parse_markdown(kind: str, elder_id: str, text: str) -> WikiPage:
    """把 Markdown 读回 WikiPage。

    容错优先：认不出的行直接忽略，而不是报错 ——
    这份文件允许人手改，改出点格式问题不该让整个 wiki 失效。
    """
    page = WikiPage.empty(kind, elder_id)
    current: WikiSection | None = None
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("<!--"):
            continue
        if stripped.startswith("# ") and not stripped.startswith("## "):
            continue  # 一级标题（文档名）
        if stripped.startswith("## "):
            title = stripped[3:].strip()
            # 只认预定义的节；LLM 自创的标题忽略掉（防止文档被写乱）
            if title in page.sections:
                current = page.sections[title]
            else:
                current = None
            continue
        if stripped.startswith("- "):
            if current is None:
                continue
            body = stripped[2:].strip()
            if body:
                current.items.append(WikiItem(text=body))
            continue
        # 其它情况：当作上一节的续行（人工编辑时容易写成多行）
        if current is not None and stripped:
            if current.items:
                current.items[-1].text += " " + stripped
    return page
