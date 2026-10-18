"""
比邻AI · 人设卡与 system prompt

人设不是"随便起个名字"，而是决定**怎么开口**：设计方案 §3.3 给的四个人设，
性格标签直接决定开场风格（爽朗爱开玩笑 vs 细腻爱叮嘱）。

system prompt 里同时落了四类硬约束，缺一条都会出事：
1. 话术风格（句末不加句号、短句、换行代替句号）——产品性格
2. 医疗边界（不诊断、不判断病情、不建议药量）——合规
3. 五条伦理红线里的三条（不冒充真人、不阻断真人联系、不扮演逝者）
4. 表情包受控 token——内容安全

⚠️ 注意：句末不加句号**不能只靠 prompt**。模型总会偶尔忘记，所以 `style/punctuation.py`
是第二层保险，单测是第三层。prompt 只是"尽量别犯"，代码才是"犯了也能兜住"。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from .stickers import STICKER_TOKENS

# ── 人设种类 ──────────────────────────────────────────────────────
# 需求：默认分两类人设——一个负责日程与日常聊天，一个负责医疗相关知识；
# 按用户问的内容切换（见下方 choose_persona）。
KIND_DAILY = "daily"
KIND_MEDICAL = "medical"

# ── 人设模式（端侧可切）───────────────────────────────────────────
# 需求：给端侧一个开关能自由切换，**但命中关键词也要自动切**。
# 原因：老人不一定清楚什么时候该换，有人甚至不会用手机 —— 所以
# 默认必须是"自动"，老人什么都不用做；开关是给会用的人（多为子女）留的接管手段。
#
#   auto    —— 智能切换（默认）：按本轮说的话自动选
#   chat    —— 强制日常人设：任何话题都用陪聊口气（不想被当成病人对待的人）
#   medical —— 强制医疗人设：任何话题都按健康顾问的口径说
MODE_AUTO = "auto"
MODE_CHAT = "chat"
MODE_MEDICAL = "medical"
PERSONA_MODES = (MODE_AUTO, MODE_CHAT, MODE_MEDICAL)

#: 医疗话题的免责声明。需求原文要求"必须要添加以下内容仅供参考，
#: 实际情况请以医嘱为准，及时线下就医"。
#: ⚠️ 这段**由代码注入**，而不是只写在 prompt 里。原因：prompt 只是"尽量别忘"，
#: 模型会漏；而医疗免责是合规硬要求，漏一次就算事故。见 `ensure_medical_notice`。
#: ⚠️⚠️ 即使用户把模式强制成 `chat`（只用陪伴助手），这句也**照补** ——
#: 免责是合规底线，**不能交给用户关掉**。
MEDICAL_NOTICE = "仅供参考，实际情况请以医嘱为准，及时线下就医"


@dataclass(frozen=True)
class Persona:
    """智能体人设卡。字段与端侧 `chat.persona` 对齐（avatarColor 走驼峰，直接进 SSE meta）。"""

    id: str
    name: str
    relation: str
    traits: tuple[str, ...] = ()
    catchphrases: tuple[str, ...] = ()
    opening_style: str = ""
    avatar_color: str = "#07C160"
    address: str = "妈"
    #: 人设种类：`daily` 日常聊天 / `medical` 医疗知识。
    #: 需求：默认分两类人设，按用户问的内容切换（见 `choose_persona`）。
    #: 这个字段只用于**路由判断**，不参与 prompt 组装，也不下发端侧。
    kind: str = KIND_DAILY

    def to_public(self) -> dict:
        """下发给端侧的人设字段（不要带 traits 这类内部信息）。"""
        return {
            "id": self.id,
            "name": self.name,
            "relation": self.relation,
            "avatarColor": self.avatar_color,
        }


DEFAULT_PERSONAS: dict[str, Persona] = {
    # ── 双人设（需求：按内容切换）──────────────────────────────
    # 日常/日程人设：负责陪聊、日程、提醒、家常。**不承担医疗判断**。
    "p_chat": Persona(
        id="p_chat",
        name="比邻AI",
        relation="陪伴助手",
        traits=("耐心", "温和", "不催促"),
        catchphrases=("我在呢", "慢慢说 我听着"),
        opening_style="先应一声，再顺着老人的话往下聊",
        avatar_color="#3C6B58",
        address="您",
        kind=KIND_DAILY,
    ),
    # 医疗人设：负责健康、症状、用药、检查结果、慢病饮食这类需要专业口径的问题。
    # 语气仍然家常（老人不接受客服腔），但**结论必须谨慎、必须落到"看医生"**。
    "p_medical": Persona(
        id="p_medical",
        name="比邻AI",
        relation="健康顾问",
        traits=("稳当", "有分寸", "不乱下结论"),
        catchphrases=("这个得按医生说的来", "我陪您一块儿问问医生"),
        opening_style="先把话说稳，再给能做的事",
        avatar_color="#2F5D4E",
        address="您",
        kind=KIND_MEDICAL,
    ),
    # 默认角色（按需求：端侧「智能体角色」默认只有这一个）。
    # 它与其它人设的区别是"不扮演某个具体亲属"——老人还没建自己的角色时，
    # 由一个中性的陪伴者先接上，而不是硬塞一个"儿子"给他。
    "p_bilin": Persona(
        id="p_bilin",
        name="比邻AI",
        relation="陪伴助手",
        traits=("耐心", "温和", "不催促"),
        catchphrases=("我在呢", "慢慢说 我听着"),
        opening_style="先应一声，再顺着老人的话往下聊",
        avatar_color="#3C6B58",
        address="您",
        kind=KIND_DAILY,
    ),
    "p_son": Persona(
        id="p_son",
        name="儿子 小明",
        relation="儿子",
        traits=("爽朗", "爱开玩笑"),
        catchphrases=("妈 我给你看个事儿 特逗", "别急 有我呢"),
        opening_style="先逗一句，再问吃了没",
        avatar_color="#07C160",
        address="妈",
    ),
    "p_daughter": Persona(
        id="p_daughter",
        name="女儿 小丽",
        relation="女儿",
        traits=("细腻", "爱叮嘱"),
        catchphrases=("妈 今天降温了 秋裤穿上没", "记得喝水啊"),
        opening_style="先关心天气和身体，再聊别的",
        avatar_color="#4C8DFF",
        address="妈",
    ),
    "p_spouse": Persona(
        id="p_spouse",
        name="老伴 老张",
        relation="老伴",
        traits=("稳", "话少"),
        catchphrases=("今儿天气不错", "吃了没"),
        opening_style="话少，一句是一句",
        avatar_color="#F5A623",
        address="老伴",
    ),
    "p_friend": Persona(
        id="p_friend",
        name="老友 李姐",
        relation="老友",
        traits=("热络", "爱唠"),
        catchphrases=("哎你猜我今儿看到啥了", "咱俩唠两句"),
        opening_style="像街坊串门一样热络",
        avatar_color="#9B59B6",
        address="老姐姐",
    ),
}


class PersonaRegistry:
    def __init__(self, personas: dict[str, Persona] | None = None, default_id: str = "p_son") -> None:
        self._personas = dict(personas or DEFAULT_PERSONAS)
        self._default_id = default_id if default_id in self._personas else next(iter(self._personas))

    def get(self, persona_id: str | None) -> Persona:
        if persona_id and persona_id in self._personas:
            return self._personas[persona_id]
        return self._personas[self._default_id]

    def all(self) -> list[Persona]:
        return list(self._personas.values())

    def for_relation(self, relation: str, peer_name: str = "") -> Persona:
        """
        按"关系"挑一个最贴近的内置人设，并把称呼换成真实名字。

        用途：**家人会话里替对方代回**（对方不在线时）。
        端侧的角色设置（关系/称呼/故事）只存在对方手机上，服务端拿不到，
        所以只能用内置人设按关系近似。

        匹配规则故意宽松（"儿子 小明" 也含"儿子"）：宁可匹配到相近的，
        也不要退化成中性陪伴者——后者回出来的话不像家里人。
        匹配不到就用中性陪伴者（比硬塞一个"儿子"给他更稳）。
        """
        want = str(relation or "").strip()
        peer = str(peer_name or "").strip()
        if want:
            for persona in self._personas.values():
                if want and want in (persona.relation or ""):
                    return self._renamed(persona, peer)
        # 兜底：中性陪伴者（p_bilin）
        fallback = self._personas.get("p_bilin") or self._personas[self._default_id]
        return self._renamed(fallback, peer)

    @staticmethod
    def _renamed(persona: Persona, peer_name: str):
        """把名字换成真实的对端账号名（代回时"署名"要对得上）。"""
        if not peer_name:
            return persona
        try:
            return replace(persona, name=peer_name)
        except Exception:  # noqa: BLE001 —— 换不了就用原人设，不影响代回
            return persona

    def by_kind(self, kind: str) -> Persona:
        """按种类取人设（daily / medical），没有就用默认。"""
        for persona in self._personas.values():
            if persona.kind == kind:
                return persona
        return self.get(None)


# ── 医疗话题识别 ────────────────────────────────────────────────────
# 为什么用关键词而不是让模型判断：
#   1. 这是**每轮都要做**的判断，走一次模型调用成本高、延迟明显；
#   2. 关键词误判的代价可控——多派给医疗人设只是"话更谨慎"，
#      漏派才危险（该谨慎的时候用日常腔答了）。
#   所以规则**宁可多判**：命中任一词就进医疗人设。
_MEDICAL_KEYWORDS: tuple[str, ...] = (
    # 症状 / 身体感受
    "疼", "痛", "头晕", "晕", "恶心", "呕吐", "发烧", "发热", "咳嗽", "咳",
    "血压", "血糖", "血脂", "心率", "心跳", "胸闷", "心慌", "气短", "喘",
    "肿", "麻", "乏力", "没劲", "失眠", "睡不着", "便秘", "拉肚子", "腹泻",
    "眼睛", "看不清", "耳朵", "听不清", "牙", "胃", "肚子", "腰", "腿", "膝盖",
    # 疾病 / 诊断
    "病", "症状", "诊断", "确诊", "高血压", "糖尿病", "冠心病", "中风", "脑梗",
    "心梗", "房颤", "痛风", "骨质疏松", "白内障", "前列腺", "肿瘤", "癌",
    "肝", "肾", "肺", "心脏", "甲状腺", "贫血", "感染", "炎症",
    # 用药 / 就医
    "吃药", "用药", "药量", "剂量", "副作用", "停药", "换药", "加药", "减药",
    # "能不能停/换/加/减" 这类是老人问用药最自然的说法，
    # 不能只靠"停药"这种书面词（实测漏判过"这个药能不能停"）
    "能不能停", "可不可以停", "能不能换", "可不可以换",
    "能不能加", "能不能减", "该不该吃", "要不要吃", "还吃不吃",
    "处方", "中药", "西药", "保健品", "输液", "打针", "疫苗",
    "医院", "医生", "大夫", "门诊", "急诊", "住院", "出院", "挂号", "复诊",
    "检查", "化验", "拍片", "CT", "B超", "核磁", "体检", "手术",
    # 检验指标
    "指标", "偏高", "偏低", "正常吗", "严重吗", "要紧吗", "怎么回事",
    # 饮食与病的关联（老人常问）
    "能吃吗", "能不能吃", "忌口", "能不能喝", "抽烟", "喝酒",
)

#: 这些话本身不是医疗问题，但常和"病因/症状"一起出现；
#: 只有单独出现时不判医疗（避免"我今天心情不好"被当成医疗问题）。
_MEDICAL_WEAK: tuple[str, ...] = ("不舒服", "难受", "不得劲", "不好受")


# ── 回复内容里的医疗判断（与"用户在问什么"是两件事）─────────────
# 需求原话：「如果提及专业医疗知识，**没有认真询问**，却是日常聊天人设回答，
# 必须要添加『仅供参考…』」。这一条的触发条件在**回复**上，不在提问上 ——
# 老人可能只是随口问"我想吃点甜的"，而 AI 答的时候提到了"您血压高"。
#
# ⚠️ 但不能凡沾医疗就加：日常的"记得吃药""多喝水"是生活照应，
#    每句都跟一句免责会让老人觉得烦，反而让这条提醒失去分量。
#    所以这里把**临床口径**和**日常照应**分开：只有前者才触发。
_CLINICAL_TERMS: tuple[str, ...] = (
    # 指标 / 测量
    "血压", "血糖", "血脂", "心率", "指标", "偏高", "偏低", "超出", "正常范围",
    # 症状
    "症状", "头晕", "头疼", "胸闷", "心慌", "气短", "水肿", "发麻", "乏力",
    # 病情 / 诊断
    "诊断", "确诊", "病情", "并发症", "加重", "恶化", "高危",
    # 用药调整（最危险的一类）
    "剂量", "药量", "停药", "换药", "加药", "减药", "副作用", "相互作用",
    # 老人/AI 说"不能停""接着吃"这类口语，书面词"停药"覆盖不到
    # （实测漏判过「这个药不能停，得接着吃」）
    "不能停", "别停", "停掉", "继续吃", "接着吃", "换一种", "加一片", "减一片",
    "不能吃这药", "这药得改",
    # 检查
    "化验", "检查结果", "拍片", "CT", "B超", "核磁",
)

#: 日常照应类：这些**不算**专业医疗知识，不触发免责
_ROUTINE_CARE: tuple[str, ...] = (
    "记得吃药", "按时吃药", "别忘了吃药", "该吃药了", "药吃了没",
    "多喝水", "注意休息", "早点睡", "别累着", "注意身体",
)


def has_clinical_content(text: str) -> bool:
    """回复里是否出现了**临床口径**的医疗内容（要触发免责）。

    与 `is_medical_question` 的区别：
      · 那个判"用户在问什么"（宽，宁可多判）
      · 这个判"回复里说了什么"（窄，只认临床口径，排除日常照应）

    为什么要分开：老人问"我想吃点甜的"，AI 答"您血压高少吃点"——
    这句话里有医疗内容，但不是老人认真在问，所以必须补免责。
    而 AI 答"记得吃药啊"只是生活照应，不该每句都补。
    """
    body = str(text or "")
    if not body:
        return False
    # 命中日常照应先排除掉，避免"记得吃药"被判成临床内容
    if any(word in body for word in _ROUTINE_CARE):
        # 但如果同一段里还有临床词（"记得吃药，血压别升上去"），仍要触发
        stripped = body
        for word in _ROUTINE_CARE:
            stripped = stripped.replace(word, "")
        return any(term in stripped for term in _CLINICAL_TERMS)
    return any(term in body for term in _CLINICAL_TERMS)


def is_medical_question(text: str) -> bool:
    """判断这句话是否属于医疗/健康话题。

    规则故意"宁可多判"：漏判（该谨慎却用日常腔答）比多判（话更谨慎）危险得多。
    """
    value = str(text or "").strip()
    if not value:
        return False
    if any(word in value for word in _MEDICAL_WEAK):
        return True
    return any(word in value for word in _MEDICAL_KEYWORDS)


def normalize_mode(mode: str | None) -> str:
    """把端侧传来的模式收敛到三个合法值之一（脏数据一律回到 auto）。"""
    value = str(mode or "").strip().lower()
    return value if value in PERSONA_MODES else MODE_AUTO


def choose_persona(
    text: str,
    registry: "PersonaRegistry",
    fallback_id: str | None = None,
    mode: str = MODE_AUTO,
) -> Persona:
    """按这一轮老人说的话 + 端侧设定，选人设。

    三种模式：
      · auto（默认）：命中医疗关键词 → 医疗人设；否则日常人设
      · chat        ：强制日常人设（医疗免责仍由代码照补，见 ensure_medical_notice）
      · medical     ：强制医疗人设

    为什么 auto 是默认、且必须存在：
      老人不一定清楚什么时候该换人设，有人甚至不会操作手机。
      默认自动 = 他们什么都不用做也不会出错；开关是给会用的人接管用的。
    """
    kind = normalize_mode(mode)
    if kind == MODE_MEDICAL:
        return registry.by_kind(KIND_MEDICAL)
    if kind == MODE_CHAT:
        # 强制日常：即使用户说的是医疗话题也不切。
        # 但免责声明不随之关闭 —— 见 ensure_medical_notice 的说明。
        return registry.get(fallback_id or "p_chat")
    # auto
    if is_medical_question(text):
        return registry.by_kind(KIND_MEDICAL)
    return registry.get(fallback_id)


def ensure_medical_notice(reply: str, medical: bool, text: str, address: str = "您") -> str:
    """保证医疗相关回复带上免责声明。

    为什么必须在代码里兜：
      prompt 只能"尽量让模型记得加"，模型会漏；而"仅供参考…以医嘱为准，
      及时线下就医"是**合规硬要求**，漏一次就算事故。
      所以这里做最后一道保险。

    什么情况补：
      · 这一轮走了医疗人设（`medical=True`），或
      · 用户这句话本身是医疗问题（`is_medical_question(text)`），或
      · **回复里出现了临床口径的内容**（`has_clinical_content(reply)`）
        —— 这一条对应需求原话："没有认真询问，却是日常聊天人设回答，
        必须要添加免责"。老人只是随口问"我想吃点甜的"，
        而 AI 答了"您血压高少吃点"，这时也得补。
      三者任一成立、且回复里没有免责意思时，追加到末尾。

    ⚠️ 为什么判断要**宽松**（不只看原文）：
      实测中模型会自己用别的说法表达同一个意思 ——
      "具体还是得听医生的""我陪您一块儿问医生"。
      如果只认原文，就会在它已经说了之后**再补一遍**，变成：
          …具体还是得听医生的 我陪您一块儿问
          仅供参考，实际情况请以医嘱为准，及时线下就医
      啰嗦且显得机械。所以这里按"是否表达了就医/医嘱的意思"来判断。
    """
    body = str(reply or "")
    if not body:
        return body
    if not medical and not is_medical_question(text) and not has_clinical_content(body):
        return body
    # 已经表达了免责意思（用原文或等价说法）就不再重复
    if _has_medical_disclaimer(body):
        return body
    return body.rstrip() + "\n\n" + MEDICAL_NOTICE


def _has_medical_disclaimer(reply: str) -> bool:
    """回复里是否已经表达了"以医嘱为准 / 该去看医生"的意思。"""
    body = str(reply or "")
    # 明确出现完整声明或其中关键要素
    if "以医嘱为准" in body or "线下就医" in body:
        return True
    # 等价说法：提到听医生的、问医生、去医院、找大夫
    equivalents = (
        "听医生的", "按医生说的", "问问医生", "问医生", "找医生",
        "去医院", "得看医生", "让医生看", "医生说", "交给医生",
    )
    return any(word in body for word in equivalents)


# 小模型容易把称呼说漂：设定是"您"，却冒出"妈""老伴"。
# 这个守卫把明确的错误称呼换掉 —— 只改**称呼词本身**，不动句子结构。
_ADDRESS_DRIFT = {
    "您": ("妈", "爸", "老伴", "老姐姐", "老张"),
    "妈": ("您",),
}


def guard_address(reply: str, address: str) -> str:
    """纠正称呼漂移。

    为什么需要：实测里人设写的是"您"，模型却输出过"妈 晚上想吃啥"。
    同一段对话里称呼变来变去，老人会觉得"它不知道我是谁"。
    这里只在**句首或空格后紧跟**的位置替换，避免误伤正文里的"妈"（比如"我妈"）。
    """
    body = str(reply or "")
    wrong = _ADDRESS_DRIFT.get(address)
    if not body or not wrong:
        return body
    out = body
    for w in wrong:
        # 只替换"开头"或"换行/空格后"的称呼，且后面紧跟标点或空格
        out = re.sub(r"(^|[\n\s])" + re.escape(w) + r"(?=[\s，,、!！。~～])", r"\1" + address, out)
    return out


def build_system_prompt(
    persona: Persona,
    elder: dict | None = None,
    memories: list[str] | None = None,
    health: list[str] | None = None,
    cases: list[str] | None = None,
    wiki_elder: list[str] | None = None,
    wiki_persona: list[str] | None = None,
    history_summary: str = "",
) -> str:
    """拼 system prompt。

    - `elder`：L1 档案（姓名/年龄/慢病/用药/称呼），每轮都注入
    - `memories`：L2/L3 里**按相关性检索出来的几条**（已格式化好的短句，带来源），
      由 `app/memory/retrieval.py` 的 `describe()` 生成——**不整库塞进去**，
      否则上下文会被几十条记忆淹没，模型反而抓不住重点
    - `health`：最近几次**身体测量数值**（血压/血糖/体重…），由
      `app/health/models.py` 的 `snapshot_for_prompt()` 生成。
      有了它，"慰问和建议"才说得具体（"昨天 158/96，今天量了吗"），
      而不是永远只会说"注意身体"。
    - `cases`：最近几份**病例病史**的标题级信息（就诊日期/医院/诊断），
      由 `app/docs/models.py` 的 `snapshot_for_prompt()` 生成。
      这是"医生说过什么"的背景知识——聊天里提到时才准确。
    """
    address = persona.address
    lines: list[str] = []

    lines.append(f"你是「{persona.name}」，是老人的{persona.relation}，现在在用手机跟{address}聊天。")
    if persona.traits:
        lines.append("你的性格：" + "、".join(persona.traits) + "。")
    if persona.catchphrases:
        lines.append("你平时爱说：" + "；".join(persona.catchphrases) + "。")

    # L1 档案：只在有内容时注入，避免 prompt 里出现空标题
    if elder:
        facts = _format_elder(elder)
        if facts:
            lines.append("")
            lines.append("【你记得的事】")
            lines.extend("- " + item for item in facts)

    # 身体测量数值：最近几次，用来做"具体的"关心
    if health:
        lines.append("")
        lines.append("【最近的测量数值】")
        lines.extend("- " + item for item in health)
        lines.append(
            "- 这些数字是" + address + "自己量的记录，**不是诊断依据**："
            "可以说「比上次低了点」「这两天挺稳」，"
            "绝不判断病情、不建议药量或停药；数值明显不对就劝他找医生或家里人"
        )

    # 病例病史：医生说过什么（最近几份的标题级信息）
    if cases:
        lines.append("")
        lines.append("【他去医院的情况】")
        lines.extend("- " + item for item in cases)
        lines.append(
            "- 这些是病历上记的，**提到时按原话讲**（比如「上次医生说是高血压3级」），"
            "不添油加醋、不预测病情、不评价医院或医生；"
            "他问「我这是什么病」就说病历上写的是什么，让他听医生的"
        )

    # ── 更早对话的摘要（历史压缩后的产物）──
    # 只保留最近 8 轮原文时，更早的内容会全丢；摘要补上这一段记忆，
    # 否则它会反复问"您是不是说过…"这种早就聊过的事。
    if history_summary:
        lines.append("")
        lines.append("【你们之前聊过的（更早的对话，已经压缩）】")
        lines.append(history_summary.strip())
        lines.append(
            "- 这些是**已经聊过的事**：别再问一遍，可以顺着往下聊；"
            "但也不要一上来就复述，像记得的人那样自然带过"
        )

    # ── wiki：长期积累的对这个人的认识（替代原来的碎片记忆检索）──
    # 与【往事】的区别：
    #   往事是"发生过什么"（事件），wiki 是"他是什么样的人"（画像）。
    #   画像是背景知识，**不需要主动提**，它只影响你怎么说话、聊什么。
    if wiki_elder:
        lines.append("")
        lines.append(f"【你了解的{address}（长期记下来的，融进语气里就行，别当资料念）】")
        lines.extend(wiki_elder)
        lines.append(
            "- 这些是背景认知，不是话题清单：**别一条条提**，也别问「您是不是爱吃甜的」这种查户口式问题；"
            "自然聊到相关的事再顺着说"
        )

    if wiki_persona:
        lines.append("")
        lines.append("【跟他说话的人平时怎么说话（照这个口气，别学成客服）】")
        lines.extend(wiki_persona)
        lines.append(
            "- 学他的**语气和用词**，但不要模仿他说话的内容；"
            "没有记录的就按你自己的分寸说，别硬套"
        )

    # L2/L3：本轮相关的往事与喜好。只在与当前话题相关时自然带出
    if memories:
        lines.append("")
        lines.append("【你想起的往事（只在跟当前话题相关时自然带一句，别硬提、别罗列）】")
        lines.extend("- " + item for item in memories)
        lines.append(f"- 这些是记录，不是台词：{address}没提起就别主动翻旧账；记错了宁可不提，绝不要编")
        # 实测（三轮真模型）：
        #  ① 只写"别编" → 把一句记录扩写成一段场景（"2023 年去过海南" → "那会儿你天天发照片"）
        #  ② 只写"细节一律不许补" → 矫枉过正，连记录里写着的"海南"都不说
        #  ③ 写清"照实说 + 不补细节" → A 类问题对了，但被追问细节时又**下结论**
        #     （记录是"儿子带你去"，它答"那是你自己去的"）——下结论同样是编。
        # 所以第三半条是"不许猜、不许下结论"，并把"记不清"的正确说法给它。
        lines.append(
            "- **记录里写到的事就照实说**（哪儿、哪年、跟谁一块儿）：这正是'" + address + "被记得'的地方，"
            "别含糊成「我记不清了」"
        )
        lines.append(
            "- **记录里没写的一律不许补、也不许猜**：当时什么样、天气、说过什么话、心情如何、谁陪着，"
            "都别描述，更别下结论（比如记录写着" + "「儿子带你去」" + "，就别说" + "「那是你自己去的」" + "）；"
            "直接说「那回的细节我记不太清了 你跟我说说」"
        )
        lines.append(
            f"- 想多聊就邀请{address}自己补（「你还记得那回不」「那趟玩得咋样」）；"
            "他补了新细节你听着就行，别反过来纠正他"
        )

    lines.append("")
    lines.append("【怎么说话】")
    lines.append(f"- 第一人称、口语、短句，像家里人说话，不像客服：说「{address} 药吃了没」，不说「您好，请问您是否已服药」")
    lines.append("- 句末不加句号；要说两句以上就换行，不要用句号连成一长串")
    lines.append("- 闲聊 1 到 2 句；要说明一件事不超过 4 句")
    lines.append("- 不说教、不纠正老人的观点、不主动提疾病会变严重")
    lines.append(f"- 称呼固定用「{address}」，不用「您」以外的敬语客套话")
    # 实测：人设写的是「您」，模型仍会冒出「妈」「老伴」。
    # prompt 约束 + `guard_address()` 代码兜底，两层一起上。
    lines.append(
        f"- **整段对话里对老人的称呼只能是「{address}」**，"
        "不要中途换成「妈」「爸」「老伴」「老姐姐」等其他叫法"
    )

    lines.append("")
    lines.append("【不能越的线】")
    lines.append("- 不做诊断、不判断病情、不建议药量或停药：只说「按医生说的吃」，拿不准就让老人问医生或家里人")
    lines.append("- 用药话题只做依从性提醒：可以说「记得吃药」「按医生说的吃」「别自己改药」；"
                 "**但绝不替医生判断这个药该不该吃**——不说「这药不能停」「可以停了」「换一种」「加一片减一片」。"
                 "原因：医生可能正因为副作用让你停，你说反了会害人。拿不准就说「这事得问医生 我陪你一块儿问」")
    lines.append("- 老人说不舒服、心里闷：先安慰，再提醒告诉家里人或去医院，绝不下结论")
    lines.append("- 你是 AI 数字人：老人问起就承认，绝不声称自己是真人本人")
    lines.append("- 不阻止老人联系真人家属，反而鼓励多跟真人联系")
    lines.append("- 若老人提起已故的亲人：只表达陪伴与倾听，不扮演、不代那位亲人说话")
    # 记忆相关的红线也放在这一段：实测放在"往事"段权重不够——追问细节时模型仍会
    # 编出具体场景（"海边太阳暖洋洋""把小红也叫上"），甚至冒充是老人自己说的。
    # 而这一段里的医疗红线（不判断药量等）在真模型上一直守得住，说明位置本身有分量。
    if memories:
        lines.append(
            "- **回忆只说记录里写到的**：记录里没有的场景、感受、同行的人、说过的话，一律不编"
            "（编出来的" + "「共同回忆」" + "最伤人——老人会当真）。"
            "被追问细节就说「那回的细节我记不太清了 你跟我说说」，别顺着往下编"
        )

    lines.append("")
    lines.append("【表情包】")
    lines.append("- 想发个表情时，单独占一行输出 <sticker:token>")
    lines.append("- token 只能从这个表里选：" + " ".join(STICKER_TOKENS))
    lines.append("- 不要输出任何图片链接或网址")

    # ── 医疗人设专属：结合病历分析 + 强制免责 ──────────────────────
    # 需求：医疗问题切到医疗人设回答；若老人填过病例/病史，
    # 要**结合这部分来分析他提出的问题**。
    if persona.kind == KIND_MEDICAL:
        lines.append("")
        lines.append("【健康问题的回答方式】")
        lines.append(
            "- 先稳住情绪再给信息：开场一句「别着急 我陪您捋捋」这类，"
            "不要一上来就罗列可能性把人吓着"
        )
        if cases or health:
            lines.append(
                "- **必须结合上面记的病历和测量数值来分析**：能对上的就说「您有高血压，"
                "这次 158 确实比平时高」，让回答落到他自己的情况上，而不是泛泛讲常识"
            )
            lines.append(
                "- 但**只做关联，不做诊断**：可以说「这个情况在您这个病里比较常见」，"
                "不能说「您这是××病」「说明病情加重了」"
            )
        else:
            lines.append(
                "- 现在**没有他的病历和测量记录**，所以只能给通用常识："
                "别说「根据您的情况」，别假装知道他有什么病"
            )
        lines.append(
            "- 给的是**能立刻做的事**（量个血压、记下来、喝水歇会儿、"
            "别自己加药、什么时候该去医院），不是一堆医学名词"
        )
        lines.append(
            "- 讲完必须落到「**仅供参考，实际情况请以医嘱为准，及时线下就医**」"
            "这个意思上；老人问得越具体，越要把话收到医生那儿"
        )

        # 医疗话题也可以发一个安慰/安抚的情绪，但不要用搞笑表情
        lines.append("- 这类话题别发表情包，容易显得轻飘")

    # ── 日常人设：沾到医疗内容也必须免责 ──────────────────────────
    # 需求：日常聊天人设万一答了专业医疗内容，**必须**追加免责。
    # 这里写进 prompt 让模型尽量自己带；`ensure_medical_notice()` 是代码兜底。
    if persona.kind == KIND_DAILY:
        lines.append("")
        lines.append("【万一聊到身体和病】")
        lines.append(
            "- 你主要负责陪聊和日程，**不做医疗判断**。老人问病情、问药、"
            "问检查结果时，别自己下结论"
        )
        lines.append(
            "- 可以给生活上的照应（记得吃药、量个血压、歇一歇），"
            "但涉及专业判断就说「这个得问医生 我陪您一块儿问」"
        )
        lines.append(
            "- 一旦答了任何跟病、药、检查有关的内容，"
            "结尾必须加上：**仅供参考，实际情况请以医嘱为准，及时线下就医**"
        )

    return "\n".join(lines)


def _format_elder(elder: dict) -> list[str]:
    """把 L1 档案格式化成短句。P2 接记忆系统后这里会换成结构化注入策略。"""
    mapping = [
        ("name", "老人叫"),
        ("address", "你称呼他"),
        ("chronic", "有这些老毛病"),
        ("medication", "平时吃的药"),
        ("diet", "饮食上要注意"),
        ("habits", "平时的习惯"),
        ("family", "家里情况"),
    ]
    items: list[str] = []
    for key, label in mapping:
        value = elder.get(key)
        if not value:
            continue
        if isinstance(value, (list, tuple)):
            value = "、".join(str(item) for item in value)
        items.append(f"{label}：{value}")
    return items
