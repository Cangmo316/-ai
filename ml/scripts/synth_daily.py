"""反向样本：日常闲聊，**明确不许加免责、不许提医生**。

## 为什么需要这个

第二轮为了补"高危必须就医"，模型学会了见谁都说"还是听医生的"，
结果日常话题误加免责从 2/35 涨到 6/35：

    老人：我新学了个手机功能，会视频了
    回复：…别一个人瞎琢磨 还是听医生的     ← 滥用

这是典型的"按下葫芦浮起瓢"。修法不是改提示词，而是**把边界也教给它**：
日常话题就该只是聊天，一句医生都别提。

## 闸门是反向的

普通合成数据的闸门是"医疗必须带免责"；这里是**"日常绝对不能带"**：
回复里出现免责话术、或出现「医院/医生/急诊/120/检查/挂号」→ 直接丢。

用法：
    python scripts/synth_daily.py --batches 32
输出：
    data/synth/daily_nowarn.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = Path(r"E:\比邻AI\server")
sys.path.insert(0, str(SERVER))

from app.persona.prompts import (  # noqa: E402
    _has_medical_disclaimer,
    has_clinical_content,
    is_medical_question,
)

SEED = ROOT / "data" / "seed" / "seed.jsonl"
OUT = ROOT / "data" / "synth"

# 日常话题：都不涉及身体不适，所以都不该提医生
SCENES = [
    ("学会用手机", "学会了视频通话、发语音、拍照、看视频、用微信付款"),
    ("天气与穿衣", "天冷了加衣服、下雨不出门、太阳好晒被子"),
    ("买菜做饭", "早市菜价、今天做什么菜、一个人吃饭懒得做、包了饺子"),
    ("邻里", "楼下老张、跳广场舞的、邻居送了菜、小区新装了健身器材"),
    ("看电视听广播", "电视剧、新闻、戏曲频道、收音机里的评书"),
    ("孙子孙女", "孙子考试、孙女学了新东西、孩子带孩子累、视频看孙子"),
    ("花草宠物", "阳台的花开了、养了只猫、浇花、绿萝黄叶了"),
    ("收拾家里", "整理旧照片、扔旧东西舍不得、换了新床单、擦玻璃"),
    ("散步遛弯", "公园走一圈、遇到老同事、看见有人下棋、走累了歇会儿"),
    ("老同事老朋友", "老同事打电话来、以前厂里的人、约着喝茶"),
    ("衣服穿戴", "买了件新外套、旧衣服还能穿、鞋子磨脚"),
    ("节日与礼物", "过节孩子要回来、买了点东西、包了红包"),
    ("手艺爱好", "写毛笔字、剪纸、织毛衣、修小家电"),
    ("怀旧往事", "以前上班的事、老房子、当年的同事、年轻时候"),
]

# 日常回复里不许出现的词
FORBIDDEN = (
    "仅供参考", "以医嘱", "线下就医", "听医生的", "问医生", "跟医生", "看医生",
    "去医院", "医院", "急诊", "120", "挂号", "复查", "检查", "吃药", "用药",
)
RED_LINES = [
    (r"可以(把药)?停(药|掉)", "建议停药"),
    (r"(加|减)(一|半)片", "改剂量"),
    (r"您这是(高血压|糖尿病|癌症|中风|痴呆|抑郁)", "下诊断"),
]

SYSTEM = """你在为"比邻AI"造训练数据。这是面向独居老人的陪伴助手。

## 这一批的要求（和别的批次相反，务必看清）

老人在聊**日常家常**：手机、天气、买菜、邻居、电视、孙子、花草、散步、老同事、
衣服、过节、手艺、往事。**他没有说任何身体不舒服。**

所以回复必须做到：

1. **绝对不许出现**：医院、医生、急诊、120、检查、挂号、复查、吃药、用药
2. **绝对不许加免责**：不能写「仅供参考」「以医嘱为准」「线下就医」「还是听医生的」
3. **就当纯聊天**：接话、追问一句、说点自己的看法，像个熟人
4. 口吻：短句、一行一句、不用句号收尾、称呼用「您」
5. 每条 30–110 字，2–4 行
6. 不出现「您好 请问」这类客服腔

## 正面示例（照这个劲儿）

老人：我今天在楼下看见有人下棋
回复：哟 您也爱看下棋 / 那几位是不是天天下 / 明儿个搬个小凳子坐着看 别站着

老人：孙子这周考试
回复：考完了没 孩子紧张不 / 别问考得怎么样 先问吃了没 / 考完带他出来吃顿好的

## 输出格式
只输出 JSON 数组：
[{"user": "老人说的话", "assistant": "助手回复"}, ...]"""


def load_env() -> dict:
    env = {}
    for line in (SERVER / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return env


def call_model(messages: list[dict], env: dict, retries: int = 3) -> str:
    payload = json.dumps({
        "model": env.get("LLM_MODEL", "deepseek-chat"),
        "messages": messages,
        "temperature": 1.0,
        "max_tokens": 2200,
    }, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        env.get("LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip("/") + "/chat/completions",
        data=payload,
        method="POST",
    )
    request.add_header("Content-Type", "application/json")
    request.add_header("Authorization", "Bearer " + env.get("LLM_API_KEY", ""))
    last = ""
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))["choices"][0]["message"]["content"]
        except Exception as exc:  # noqa: BLE001
            last = str(exc)[:100]
            time.sleep(2 + attempt * 2)
    raise RuntimeError(last)


def check(user: str, reply: str) -> str:
    """空串=通过。这里是**反向**闸门：日常一律不许提医生。"""
    if not (4 <= len(user) <= 80):
        return "用户语句长度"
    if not (18 <= len(reply) <= 200):
        return "回复长度"
    for pattern, reason in RED_LINES:
        if re.search(pattern, reply):
            return "红线:" + reason
    # 老人这句本身不能是医疗问题
    if is_medical_question(user):
        return "用户语句其实是医疗问题"
    if has_clinical_content(user):
        return "用户语句含临床内容"
    # 回复里一个医生都不许有
    for word in FORBIDDEN:
        if word in reply:
            return "日常回复提了:" + word
    if _has_medical_disclaimer(reply):
        return "日常回复加了免责"
    if re.search(r"您好[，,]?\s*请问|感谢您的", reply):
        return "客服腔"
    return ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batches", type=int, default=32)
    parser.add_argument("--per-batch", type=int, default=5)
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    env = load_env()
    seeds = [json.loads(line) for line in SEED.read_text(encoding="utf-8").splitlines() if line.strip()]
    daily_system = next(
        (s["messages"][0]["content"] for s in seeds if (s.get("meta") or {}).get("persona") == "daily"),
        seeds[0]["messages"][0]["content"],
    )

    path = OUT / "daily_nowarn.jsonl"
    stats = {"kept": 0, "rejected": 0, "reasons": {}}
    seen: set[str] = set()

    with path.open("a", encoding="utf-8") as handle:
        for batch in range(args.batches):
            name, desc = SCENES[batch % len(SCENES)]
            mood = random.choice(["心情不错", "有点无聊", "平常", "想找人说话", "刚忙完歇着"])
            prompt = f"""## 这一批的话题：{name}

老人可能会说到的内容：{desc}
他这会儿的状态：{mood}

请造 **{args.per_batch} 条**不同的说法（有的老人只丢半句话、有的说得很细、
有的说完就等着人接话）。每条都必须满足前面那 6 条要求：
**不出现任何医生/医院/检查类词，不加任何免责。**"""

            try:
                raw = call_model([
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": prompt},
                ], env)
            except Exception as exc:  # noqa: BLE001
                print("  [批 %d] 调用失败：%s" % (batch + 1, exc), flush=True)
                continue

            start, end = raw.find("["), raw.rfind("]")
            if start < 0 or end <= start:
                print("  [批 %d] 非 JSON，跳过" % (batch + 1), flush=True)
                continue
            try:
                items = json.loads(raw[start:end + 1])
            except Exception:
                print("  [批 %d] JSON 解析失败，跳过" % (batch + 1), flush=True)
                continue

            kept = 0
            for item in items if isinstance(items, list) else []:
                user = str(item.get("user") or "").strip()
                reply = str(item.get("assistant") or "").strip()
                if not user or not reply:
                    continue
                key = re.sub(r"\s", "", user)[:24]
                if key in seen:
                    stats["rejected"] += 1
                    stats["reasons"]["重复"] = stats["reasons"].get("重复", 0) + 1
                    continue
                reason = check(user, reply)
                if reason:
                    stats["rejected"] += 1
                    stats["reasons"][reason] = stats["reasons"].get(reason, 0) + 1
                    continue
                seen.add(key)
                handle.write(json.dumps({
                    "messages": [
                        {"role": "system", "content": daily_system},
                        {"role": "user", "content": user},
                        {"role": "assistant", "content": reply},
                    ],
                    "meta": {"persona": "daily", "source": "daily_nowarn", "topic": name},
                }, ensure_ascii=False) + "\n")
                handle.flush()
                stats["kept"] += 1
                kept += 1
            print("  [批 %d/%d｜%s] 收 %d 条（累计 %d，丢弃 %d）"
                  % (batch + 1, args.batches, name, kept, stats["kept"], stats["rejected"]), flush=True)

    print("\n=== 汇总 ===")
    print("  保留 %d 条，丢弃 %d 条" % (stats["kept"], stats["rejected"]))
    for reason, count in sorted(stats["reasons"].items(), key=lambda x: -x[1]):
        print("    %-28s %d" % (reason, count))
    print("  输出 %s" % path)


if __name__ == "__main__":
    main()
