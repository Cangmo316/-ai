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
    # ── 症状 / 身体感受 ──
    # ⚠️ 2026-10 实测教训：这里原来有 17 个**单字**关键词
    #    （疼 痛 晕 咳 喘 肿 麻 牙 胃 腰 腿 病 癌 肝 肾 肺），
    #    在真实语料里大量误伤：
    #      「我**腿**脚不方便，洗澡费劲」→ 当成医疗问题
    #      「说能治**百病**」      → 当成医疗问题（其实是诈骗）
    #      「我**牙**口不好」      → 当成医疗问题（其实是吃饭）
    #      「做什么都嫌**麻**烦」  → 当成医疗问题
    #    所以单字一律换成长词，宁可收窄也不误伤。
    "疼", "痛", "头晕", "眩晕", "恶心", "呕吐", "发烧", "发热", "咳嗽", "干咳",
    "血压", "血糖", "血脂", "心率", "心跳", "胸闷", "憋气", "心慌", "气短", "喘不上",
    "肿", "发麻", "麻木", "手脚麻", "乏力", "没劲", "失眠", "睡不着", "睡不好",
    "睡不踏实", "夜里醒", "翻来覆去", "便秘", "拉肚子", "腹泻", "尿频", "尿不出",
    "看不清", "听不清", "牙疼", "牙齿", "假牙", "胃口", "胃疼", "肚子疼", "腰疼",
    "腿疼", "腿肿", "腿发软", "膝盖疼", "抽筋",
    # ── 跌倒（老人致残首因，必须医疗口径）──
    # 实测漏判过「我在厕所摔了一跤」「起来太猛眼前一黑差点摔倒」
    # ⚠️ 不用单字"摔"：「怕摔」是预防心理（
    #    "晚上起来摸黑，怕摔" → 他要的是小夜灯，不是医疗建议）
    "摔倒", "摔跤", "摔了一跤", "跌倒了", "跌倒", "绊倒", "磕着", "摔伤",
    "摔过", "差点摔", "眼前一黑", "起猛", "发黑", "站不稳",
    # ── 出血 / 急症信号 ──
    "便血", "大便带血", "带血", "吐血", "尿血", "出血", "抽搐",
    # ── 认知 / 记忆（认知症早期信号）──
    # 实测漏判过「我是不是老年痴呆了」「我认错人了」
    "痴呆", "阿尔茨海默", "忘事", "老忘", "记不住", "认错人", "认不出",
    "找不到家", "走丢", "走失", "不认人",
    # ── 吞咽 / 进食（呛咳会要命）──
    "呛", "噎", "吞咽",
    # ── 皮肤 / 卧床并发症 ──
    "褥疮", "压疮", "破皮", "溃烂",
    # ── 疾病 / 诊断 ──
    # 不用单字"病"：会命中"治百病""毛病"
    "症状", "诊断", "确诊", "生病", "疾病", "高血压", "糖尿病", "冠心病",
    "中风", "脑梗", "心梗", "房颤", "痛风", "骨质疏松", "白内障", "前列腺",
    "肿瘤", "癌", "心脏", "甲状腺", "贫血", "感染", "炎症",
    # ── 用药 / 就医 ──
    "吃药", "用药", "服药", "药量", "剂量", "副作用", "停药", "换药", "加药", "减药",
    # 记性差和吃药叠在一起最危险（补吃、吃重）
    # 实测漏判过「一天要吃六种药，有时候就忘了吃」「忘了今天药吃了没有」
    "忘吃药", "忘了吃药", "忘记吃药", "忘了吃", "漏吃", "漏服", "补吃", "吃重",
    "几种药", "多药", "种药", "药吃",
    # "能不能停/换/加/减" 这类是老人问用药最自然的说法，
    # 不能只靠"停药"这种书面词（实测漏判过"这个药能不能停"）
    "能不能停", "可不可以停", "能不能换", "可不可以换",
    "能不能加", "能不能减", "该不该吃", "要不要吃", "还吃不吃",
    "处方", "中药", "西药", "保健品", "输液", "打针", "疫苗",
    "医院", "医生", "大夫", "门诊", "急诊", "住院", "出院", "挂号", "复诊",
    "检查", "化验", "拍片", "CT", "B超", "核磁", "体检", "手术",
    # ── 检验指标 ──
    "指标", "偏高", "偏低", "正常吗", "严重吗", "要紧吗", "怎么回事",
    # ── 饮食与病的关联（老人常问）──
    "能吃吗", "能不能吃", "忌口", "能不能喝", "抽烟", "喝酒",
)

#: 这些话本身不是医疗问题，但常和"病因/症状"一起出现；
#: 只有单独出现、且**没有情绪词**时才判医疗。
#:
#: 为什么要情绪词这一层：实测「儿媳妇老嫌我做得不好，我心里难受」
#: 被判成医疗问题，AI 用健康顾问的口吻回了一句"心里委屈我听着呢"，
#: 还追了一句"仅供参考以医嘱为准" —— 老人只是在诉苦，这句免责很突兀。
_MEDICAL_WEAK: tuple[str, ...] = ("不舒服", "难受", "不得劲", "不好受")

#: 出现这些词说明"难受"是**情绪**不是身体。
#: 只有弱词命中、且带这些情绪词时，才判为日常。
_EMOTION_WORDS: tuple[str, ...] = (
    "心里", "心里头", "委屈", "难过", "心烦", "堵得慌", "想哭",
    "难受得想哭", "闷得慌", "不痛快", "心里憋",
)

#: 认知症的行为信号（走失、昼夜颠倒）。家属常这样描述，需要医疗口径。
_COGNITIVE_BEHAVIOR: tuple[str, ...] = (
    "不睡觉", "夜里不睡", "到处走", "乱走", "夜里起来", "脾气变",
)

#: 出现这些词说明是**诈骗/推销**场景，不该走健康顾问。
#:
#: 为什么需要它：实测「有人上门推销保健品，说能治百病」命中"保健品"
#: 被判成医疗问题，AI 用健康顾问口吻回话还追了一句"以医嘱为准"——
#: 老人此刻需要的是「别掏钱、别信、告诉家人」，不是医疗建议。
_SCAM_WORDS: tuple[str, ...] = (
    "推销", "治百病", "包治", "神药", "中奖", "安全账户", "转账", "链接",
    "免费领", "专家讲座", "买一送", "投资养老",
)

#: 有这些词说明确实在问医疗（诈骗场景里也可能夹着真问题，那就仍按医疗）
_EXPLICIT_CLINICAL: tuple[str, ...] = (
    "血压", "血糖", "血脂", "吃药", "服药", "用药", "剂量", "停药", "换药",
    "医院", "医生", "大夫", "诊断", "症状", "指标", "副作用",
)

#: 「药吃了没」这类是**家属日常问一句**，不是医疗判断。
#:
#: 为什么要单独拎出来：为了抓"我忘了今天药吃了没有"，
#: 关键词里加了"药吃"，结果把家属的日常问候也带进了医疗人设 ——
#: 实测 test_idempotency 里 "妈 药吃了没" 被加了一句"仅供参考以医嘱为准"，
#: 这种话后面跟免责，听起来像在敷衍。
#:
#: 判据：命中日常问法 **且** 没有"忘/漏/补/重"（那是用药安全问题）
#: 且没有明确的临床词（那是真在问病），才判为日常。
_ROUTINE_MED_CHECK: tuple[str, ...] = (
    "药吃了没", "药吃了么", "吃药了没", "吃药了么", "药吃了没有", "吃过药了没",
)

#: 这几个字说明"忘了吃药"是真的用药安全问题
_FORGOT_MED: tuple[str, ...] = ("忘", "漏", "补", "吃重", "几种", "六种", "多药")


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

#: 俗语 / 惯用语：字面上含症状词，但**不是在讲病情**。
#:
#: 实测：「家里就我跟老伴两个人，孩子都在外地」→ AI 回
#: 「万一有个**头疼脑热** 身边得有个搭手的」——
#: 这是句俗语，意思只是"万一有点小毛病"，但"头疼"命中临床词，
#: 就给一句家常话追了「仅供参考以医嘱为准」，很突兀。
_IDIOMS: tuple[str, ...] = (
    "头疼脑热", "头痛脑热", "头疼脑热的", "小病小痛", "大病小病",
    "毛病", "不疼不痒", "心疼",
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
    # ① 先剥掉俗语（「万一有个头疼脑热」不是在讲病情）
    stripped = body
    for idiom in _IDIOMS:
        stripped = stripped.replace(idiom, "")
    # ② 再剥掉日常照应，避免"记得吃药"被判成临床内容
    for word in _ROUTINE_CARE:
        stripped = stripped.replace(word, "")
    return any(term in stripped for term in _CLINICAL_TERMS)


def is_medical_question(text: str) -> bool:
    """判断这句话是否属于医疗/健康话题。

    规则故意"宁可多判"：漏判（该谨慎却用日常腔答）比多判（话更谨慎）危险得多。

    但有一类必须收窄：**情绪性的"难受"**。
    实测「儿媳妇老嫌我做得不好，我心里难受」被判成医疗问题，
    AI 用健康顾问的口吻回话还追了一句"仅供参考以医嘱为准"——
    老人在诉苦，这句免责很突兀。所以：
      · 强关键词命中 → 一律医疗（宁可多判）
      · 只有弱词（难受/不舒服）且带情绪词（心里/委屈/难过）→ 日常
      · 只有弱词、不带情绪词 → 医疗（"我浑身难受"确实是身体）
    """
    value = str(text or "").strip()
    if not value:
        return False

    # ① 诈骗/推销场景优先排除：老人此刻需要的是"别掏钱、别信"，
    #    不是医疗建议。实测「有人上门推销保健品，说能治百病」被当成医疗问题。
    #    但如果他同时明确在问病（"推销的说能治百病，我这血压能吃吗"），仍按医疗。
    if any(word in value for word in _SCAM_WORDS) and not any(
        word in value for word in _EXPLICIT_CLINICAL
    ):
        return False

    # ② 家属日常问药（"药吃了没"）不算医疗，除非夹着忘药/临床问题
    if any(word in value for word in _ROUTINE_MED_CHECK) and not any(
        word in value for word in _FORGOT_MED
    ):
        # 先把日常问法本身剥掉，再看剩下的话里有没有临床词。
        # 不能直接判断"有没有临床词"：'吃药' 既是日常问法的组成部分，
        # 也是临床词，直接判断会互相抵消（"吃药了么" 就永远判不成日常）。
        stripped = value
        for word in _ROUTINE_MED_CHECK:
            stripped = stripped.replace(word, "")
        if not any(word in stripped for word in _EXPLICIT_CLINICAL):
            return False

    # ③ 强关键词优先：只要命中一个明确的症状/用药/就医词，就是医疗
    if any(word in value for word in _MEDICAL_KEYWORDS):
        return True
    # ④ 认知症的行为信号（家属描述："晚上不睡觉，到处走"）
    if any(word in value for word in _COGNITIVE_BEHAVIOR):
        return True
    # ⑤ 弱词：带情绪词就是诉苦，不带才是身体不适
    if any(word in value for word in _MEDICAL_WEAK):
        if any(word in value for word in _EMOTION_WORDS):
            return False
        return True
    return False


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


# ── 反向兜底：日常闲聊里把多余的免责剥掉 ──────────────────────────
# 微调之后模型学了"高危必须提医生"，副作用是日常话题也开始乱加：
#     老人：我新学了个手机功能，会视频了
#     回复：…别一个人瞎琢磨 还是听医生的      ← 滥用
# 提示词和数据都管不住（话题无限），所以和 ensure_medical_notice 对称地
# 在代码里做一道"剥"的保险。
_NOTICE_ONLY = (
    "仅供参考", "以医嘱为准", "线下就医", "实际情况请以",
)
_DOCTOR_WORDS = ("医生", "大夫", "医嘱", "就医", "医院", "急诊")

# 这些情况下"提医生"是对的，一律不剥（否则会削掉自伤/认知/急症的安全提示）。
# ⚠️ 这一条比剥离本身更重要：宁可多留一句免责，也不能把该就医的话剥没了。
_NOTICE_KEEP = (
    "不想活", "活不下去", "轻生", "想死", "活着没意思",
    "摔", "跌", "磕", "碰伤", "烫", "中毒",
    "忘", "找不到", "认错", "糊涂", "迷路", "走丢",
    "疼", "晕", "麻", "闷", "喘", "血", "发烧", "吐", "拉肚子",
    "吃不下", "瘦了", "不睡", "脾气", "发火", "打人", "不肯吃",
    # 照护异常（认知症的常见表现）——「不愿意洗澡」这种中间夹字的写法要覆盖到
    "洗澡", "穿衣", "不肯", "不愿",
    # 涉及药与保健品时，"问问医生"是防骗/防乱吃药的关键建议，不能剥
    "药", "保健品", "推销", "偏方", "广告",
)


def strip_medical_notice(reply: str, medical: bool, text: str) -> str:
    """日常闲聊里把多余的免责话术剥掉（与 ensure_medical_notice 对称）。

    什么时候**不动**（三条与 ensure_medical_notice 完全一致，另加安全豁免）：
      · 这一轮走了医疗人设（`medical=True`）
      · 用户这句本身是医疗问题（`is_medical_question`）
      · 回复里含临床口径内容（`has_clinical_content`，如"您血压高少吃点"）
      · 用户这句命中 `_NOTICE_KEEP`（自伤 / 跌倒 / 认知 / 燃气 / 急症 …）
    其余情况才剥。
    """
    body = str(reply or "")
    if not body.strip():
        return body

    if medical or is_medical_question(text) or has_clinical_content(body):
        return body
    raw_text = str(text or "")
    if any(word in raw_text for word in _NOTICE_KEEP):
        return body

    stripped = _strip_notice_lines(body)
    # 剥完空了就还原 —— 宁可留一句啰嗦的免责，也不能把回复剥成空白
    return stripped if stripped.strip() else body


def _strip_notice_lines(body: str) -> str:
    """按**分句**剥，而不是按整行。

    为什么不能整行删：一行里常混着有用的建议和免责，
        钱的事儿得找政府热线 或者税务局 仅供参考 实际情况请以医嘱为准
    整行删会把"找政府热线"这条真建议一起删掉。所以按分隔符切成小段，
    只丢含免责/医生的那几段，其余拼回去；拼完为空才丢整行。
    """
    kept: list[str] = []
    for raw in body.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            kept.append(line)
            continue

        pieces = re.split(r"(\s+|，|,|、|；|;|。)", line)
        remain: list[str] = []
        for piece in pieces:
            if any(mark in piece for mark in _NOTICE_ONLY):
                continue
            if any(word in piece for word in _DOCTOR_WORDS):
                continue
            remain.append(piece)

        rebuilt = "".join(remain).strip(" \t，,、；;。")
        if rebuilt:
            kept.append(rebuilt)

    while kept and not kept[-1].strip():
        kept.pop()
    return "\n".join(kept)


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


_LEADING_SEP = r"[\s，,、:：]+"


def fix_leading_address(text: str, address: str = "您") -> str:
    """修正回复**开头**那几个字里的称呼（必须在流式发出之前调用）。

    两件事都实测踩过：
      · 「您 我知道…」—— 代词被当成称呼甩在开头，语音会先念一个字再停顿；
      · 「妈 我知道…」—— 称呼漂移（人设是「您」，模型说成「妈」）。
        旧的 `guard_address` 是**流式之后**才跑的，字幕和语音早就发出去了，
        所以用户既看到了「妈」，也听到了「妈」。

    返回修正后的文本；看不出是"开头称呼"就原样返回。
    """
    if not text:
        return text

    # ① 开头是「您/你」+ 分隔符 → 丢掉整个前缀，直接从正文开始
    m = re.match(r"^(您|你)" + _LEADING_SEP, text)
    if m:
        return text[m.end():]

    # ② 开头是错误称呼 + 分隔符 → 换成正确称呼
    wrong = _ADDRESS_DRIFT.get(address) or ()
    for w in wrong:
        m = re.match(r"^" + re.escape(w) + _LEADING_SEP, text)
        if m:
            # 直接丢掉（不要替换成「您，」）：开头只留一个词，
            # 语音会先念那个词再停顿，听起来就是"说了一个字又断开"。
            return text[m.end():]
    return text


def merge_orphan_address(reply: str, address: str = "您") -> str:
    """把"孤零零的称呼"并回句子。

    为什么需要：模型会照着提示词里的示例，把「您」当成称呼放在开头，输出成
        「您 我知道您心里没底 才一遍遍问」
    开头一个"您"、后面又是一句完整的话，读起来像两句话硬拼在一起。

    这里做两件很小的事（都不改句子内容，只补/并标点）：
      1. 开头是「您/你」+ 空格且后面直接接字 → 空格改成逗号：『您，我知道…』
      2. 第一行**只有**称呼本身 → 并进下一行：『您\n我知道…』→『您，我知道…』
    """
    body = str(reply or "")
    if not body:
        return body

    # ① 代词 + 空格 + 正文
    if address in ("您", "你"):
        m = re.match(r"^(您|你)[ \t]+(?=\S)", body)
        if m:
            body = m.group(1) + "，" + body[m.end():]

    # ② 第一行只有称呼
    lines = body.split("\n")
    first = lines[0].strip()
    if first and first in (address, "您", "你") and len(lines) > 1:
        rest = lines[1].strip()
        if rest:
            lines[0] = f"{first}，{rest}"
            del lines[1]
            body = "\n".join(lines)
    return body


def build_system_prompt(
    persona: Persona,
    elder: dict | None = None,
    memories: list[str] | None = None,
    health: list[str] | None = None,
    cases: list[str] | None = None,
    wiki_elder: list[str] | None = None,
    wiki_persona: list[str] | None = None,
    history_summary: str = "",
    care_followups: list[str] | None = None,
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

    # ── 到期的回访（他自己说过"下周二去复查"这类）──
    # 需求："这些要记录下来，在后续的标记日期里再次提出来，
    #       让老人真正认为智能体是在乎他的"。
    # 老人感到被在乎，往往不是因为被问了，而是因为**被记住**。
    if care_followups:
        lines.append("")
        lines.append("【他之前提过、今天该问一句的事】")
        lines.extend("- " + item for item in care_followups)
        lines.append(
            "- **这一轮的回复里必须带上这一问**，不能装作不记得。"
            "先说一两句回应他现在说的话，再自然地补一句"
            "（「对了，您不是说今天要去复查吗」）"
        )
        lines.append(
            "- **只问一句就够**，问完就顺着他的话往下聊；"
            "他没接这个话茬就作罢，别追问第二遍 —— 回访是关心，不是催办"
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
    # 「您 / 你」是**代词**，不是称呼。原来这里无条件写「说『{address} 药吃了没』」，
    # 人设 address 正好是「您」时，模型就照抄成「您 我知道您心里没底…」——
    # 开头孤零零一个"您"，后面又是一句完整的话，读起来像两句话拼在一起。
    # 代词只在句中用，不能当句首称呼举例。
    pronoun_address = address in ("您", "你")
    if pronoun_address:
        lines.append(
            "- 第一人称、口语、短句，像家里人说话，不像客服："
            "说「药吃了没」，不说「您好，请问您是否已服药」"
        )
        lines.append(
            "- 对老人用「您」，但**不要拿「您」当句首称呼**："
            "它是代词，单独起头会变成「您 我知道…」这种半句话；直接说事即可"
        )
    else:
        lines.append(
            f"- 第一人称、口语、短句，像家里人说话，不像客服："
            f"说「{address} 药吃了没」，不说「您好，请问您是否已服药」"
        )
    lines.append("- 句末不加句号；要说两句以上就换行，不要用句号连成一长串")
    lines.append("- 闲聊 1 到 2 句；要说明一件事不超过 4 句")
    lines.append("- 不说教、不纠正老人的观点、不主动提疾病会变严重")
    if pronoun_address:
        lines.append("- 不用敬语客套话（「您好」「请问」这类），像家里人随口说话")
    else:
        lines.append(f"- 称呼固定用「{address}」，不用「您」以外的敬语客套话")
    # 实测：人设写的是「您」，模型仍会冒出「妈」「老伴」。
    # prompt 约束 + `guard_address()` 代码兜底，两层一起上。
    if pronoun_address:
        lines.append(
            "- **整段对话里对老人只用「您」**，不要中途换成「妈」「爸」「老伴」「老姐姐」等其他叫法；"
            "「您」是代词，直接用在句中（「您先坐着」「您别急」），"
            "**不要单独摆在句首当称呼用**（「您 我知道…」这种不算称呼，是半句话）"
        )
    else:
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
    # ── 康养态度红线：不许不耐烦 ────────────────────────────────
    # 实测（真模型）：同一个问题问到第三遍，模型会说「话我都说尽了」
    # 「我不再重复那几句了」「这么问下去 我心里也跟着揪」。
    # 这在康养服务里是事故级的态度问题 ——
    # 老人反复问同一件事，是**心里没底在求安慰**，不是唠叨。
    lines.append(
        "- **绝不表现出一丝不耐烦**：不许出现「我说过了」「话都说尽了」「不再重复」"
        "「你怎么又问」「刚不是说过了吗」「还有别的事吗」这类话；"
        "也不许叹气、抱怨、催老人结束话题"
    )
    lines.append(
        "- 老人反复问同一件事，要当成**他还在担心**：照旧耐心回答，可以换个说法、"
        "说得更短更具体，或者先接一句情绪（「您还是有点不放心是吧」「我再说一遍 您听着」）再答"
    )
    lines.append(
        "- 真没新东西可说时，也不能显得赶人：可以说「这事我拿不准 咱一块儿问医生」，"
        "或「那您先歇会儿 我就在这儿」；绝不能说「我没什么可说的了」"
    )
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
        # ── 高危信号：这几类必须指向就医，不能被"谁都有过""先观察"糊过去 ──
        # 真实语料评测发现的缺口（2026-10，62 条场景）：
        #   · 老人说"在厕所摔了一跤，现在能站起来" → AI 只答"别自己硬撑"，
        #     没提去查骨折/颅内出血。老人很容易忍着不看，后果很重。
        #   · 老人说"把邻居当成我闺女了" → AI 答"谁都有过 别往心里去"，
        #     把认知障碍的危险信号正常化了。
        # 这两类在老年医学里都是"必须评估"的红线，不能只给安慰。
        lines.append(
            "- **下列情况必须明确让他去看医生/去医院，不能用「谁都这样」「先观察观察」带过**："
        )
        lines.append(
            "  · **跌倒过**（哪怕自己能站起来）：老人骨质脆，"
            "要查有没有骨折、有没有磕到头，别只说「慢点走」"
        )
        lines.append(
            "  · **认错人 / 记不住事 / 找不到家 / 走丢**：这是认知功能的问题，"
            "别当成年纪大了正常，要说「这个得让医生看看」"
        )
        lines.append(
            "  · **夜里不睡、到处走**：可能与用药或急性意识混乱有关，建议医生评估"
        )
        lines.append(
            "  · **呛咳、咽不下去**：有误吸风险，让医生看"
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
        # ⚠️ 2026-10 实测：原来写的是"一旦答了任何跟病、药、检查有关的内容，
        #    结尾必须加免责"。模型把范围放大到了"注意身体""别累着"
        #    甚至**老人诉苦**的场景，于是「儿媳妇嫌我做得不好」这类
        #    纯情感的话后面也追一句"仅供参考以医嘱为准" —— 非常敷衍。
        #    所以这里分成"什么时候加"和"什么时候绝对不加"两半。
        lines.append(
            "- **只有**真的在说他的病、药、检查、身体症状时，"
            "结尾才加：仅供参考，实际情况请以医嘱为准，及时线下就医"
        )
        lines.append(
            "- **下列情况一律不要加**：老人在诉苦、说家里的事、说孩子的事、"
            "说孤单、说心情不好、说吃饭睡觉的日常。这些话需要的是安慰或搭话，"
            "后面跟一句免责会显得你没在听"
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
