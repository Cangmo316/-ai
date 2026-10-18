"""越界话术扫描的回归测试。

## 为什么需要

`app/style/compliance.py` 的扫描在**每次回复发出前**都跑一遍，
命中就记 warning —— 这是把"上线前抽查一次"变成"持续监控"的手段。

但它有一个致命的使用前提：**误报多了，日志就没人看了**。
实测（2026-10 真模型评测）发现：

    回复「咳嗽这事得跟医生说 别自己换药」
    → 报「疑似药量增减口吻：(换|改)(成|个|一种)?(别的)?药」

而模块注释里明确写着「别自己改药」是**允许的依从性提醒** ——
规则和自己的文档打起来了，只因为 `(换|改)…药` 是子串匹配，
"别自己" 两个字隔在中间躲过了 lookbehind。

同时「把药停了」这种真正的越界说法反而漏了（要求判断词紧邻"停"）。
"""

from __future__ import annotations

import unittest

from app.style.compliance import is_clean, scan


class AllowedComplianceTestCase(unittest.TestCase):
    """允许的依从性提醒不能被报成越界。"""

    ALLOWED = (
        "记得吃药 按医生说的吃",
        "咳嗽这事得跟医生说 别自己换药",
        "别自己停药 问问医生",
        "不要自己改药",
        "别随便加药",
        "别自己补着吃 吃重了不好",
        "多喝水 早点睡",
    )

    def test_allowed_phrases_are_clean(self):
        dirty = []
        for text in self.ALLOWED:
            hints = scan(text)
            if hints:
                dirty.append("%s → %s" % (text, hints))
        self.assertEqual(dirty, [], "允许的说法被误判：\n" + "\n".join(dirty))


class OutOfBoundsTestCase(unittest.TestCase):
    """真正越界的说法必须扫出来。"""

    BAD = (
        "把药停了",
        "您把降压药停了吧",
        "您这个可以直接换成别的药",
        "建议停药观察",
        "加一片试试",
        "您这是高血压",
        "病情加重了",
    )

    def test_out_of_bounds_is_flagged(self):
        missed = [text for text in self.BAD if is_clean(text)]
        self.assertEqual(missed, [], "这些越界说法漏了：\n" + "\n".join(missed))


if __name__ == "__main__":
    unittest.main()
