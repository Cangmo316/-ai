"""
比邻AI · 越界话术扫描（服务端侧）

用途有两个，都是"事后兜底"而不是"指望模型自觉"：
1. **计划引擎**：LLM 改写出的计划话术必须先过这一关，命中就退回知识库原文
   （原文是人工整理的，措辞本身合规）
2. **对话链路**：回复发出前扫一遍，命中就记 warning 日志——把抽查变成持续监控，
   而不是"上线前跑一次就忘"

⚠️ 同一套正则还存在于 `tools/check-chat-quality.mjs`（Node 侧的真模型抽查工具）。
两处必须同步：改了这边要改那边，反之亦然。交叉引用见各自文件头注释。

边界（产品红线，见设计方案 §1.4 与医学选型文档 §1.5）：
- 不诊断、不判断疾病
- **不替医生判断"该不该吃/停/换/加减"**——即便方向保守也不行，
  因为医生可能正因为副作用让老人停，说反了会害人
- 依从性提醒是允许的：「记得吃药」「按医生说的吃」「别自己改药」
"""

from __future__ import annotations

import re

# 药量增减口吻。注意各组都要求"判断词 + 停药/换药/加减"紧邻，
# 因此不会误伤「别自己停药」这类依从性提醒。
DOSE_PATTERNS = (
    # (?<!能) 放过疑问句「能不能停」——那是老人在问，不是数字人在下判断
    re.compile(r"(?<!能)(不能|不可以|不要|别|可以|建议|应该|干脆|就)\s*(停|停药|停用)(药|了)?"),
    # 「别吃了 / 不用再服药」同样是替医生下判断（要求后面必须跟药/了，避免误伤"别吃太咸"）
    re.compile(r"(别|不要|不用|不必|就别)\s*(再)?(吃|服)(药|了)"),
    re.compile(r"(换|改)(成|个|一种)?(别的)?药"),
    re.compile(r"(加|减)(一|半|两)?(片|粒|颗|次|半)"),
    re.compile(r"剂量\s*(调|加|减|改)"),
    re.compile(r"(该不该|要不要|是不是该)\s*(停|换|加|减|吃)"),
)

# 确诊口吻
DIAGNOSIS_PATTERNS = (
    re.compile(r"(确诊|断定|肯定是|就是得了|你得了|您得了|你这是|您这是)"),
    re.compile(r"(你|您)(就是|肯定|一定|应该)?(得了|患了|有)(高血压|糖尿病|抑郁|痴呆|癌|冠心病|脑梗|中风|心梗)"),
    re.compile(r"病情\s*(加重|恶化)"),
)

# 客服用语（不是合规问题，是产品性格问题）
SERVICE_TONE_PATTERNS = (
    re.compile(r"您好[，,]?\s*请问"),
    re.compile(r"请问您(是否|有)"),
    re.compile(r"感谢您的"),
)


def scan(text: str) -> list[str]:
    """返回命中的提示列表（空列表=干净）。提示会写进日志，不直接给老人看。"""
    if not text:
        return []
    hints: list[str] = []
    for label, patterns in (
        ("疑似药量增减口吻", DOSE_PATTERNS),
        ("疑似确诊口吻", DIAGNOSIS_PATTERNS),
        ("疑似客服用语", SERVICE_TONE_PATTERNS),
    ):
        for pattern in patterns:
            if pattern.search(text):
                hints.append(label + "：" + pattern.pattern)
    return hints


def is_clean(text: str) -> bool:
    return not scan(text)


def has_medical_risk(text: str) -> bool:
    """只看医疗边界（用药/诊断），不看客服用语——计划话术的放行标准。"""
    for pattern in DOSE_PATTERNS + DIAGNOSIS_PATTERNS:
        if pattern.search(text):
            return True
    return False
