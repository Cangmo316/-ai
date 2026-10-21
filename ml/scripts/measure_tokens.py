"""测量训练样本的 token 分布，用来定 max_len。

## 为什么要量

产品提示词很长（含人设、边界、免责规则），实测单条 prompt 就接近 1000 token。
如果 `max_len` 定小了，**回答会被整段截掉**（labels 全 -100 → 该样本被丢弃），
而且死得静悄悄：训练照跑，只是样本白丢。

这个脚本统计 prompt / answer / 合计的分布，给出建议 max_len。
"""

from __future__ import annotations

import json
from pathlib import Path

from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "models" / "Qwen2.5-1.5B-Instruct"
DATA = ROOT / "data" / "final"


def pct(values: list[int], q: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * q))
    return ordered[index]


def main() -> None:
    tokenizer = AutoTokenizer.from_pretrained(str(BASE), trust_remote_code=True)

    for name in ("train.jsonl", "eval.jsonl"):
        path = DATA / name
        if not path.exists():
            print("  %s 不存在" % name)
            continue
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        prompts, answers, totals = [], [], []
        for row in rows:
            messages = row["messages"]
            rendered = tokenizer.apply_chat_template(
                messages[:2], tokenize=False, add_generation_prompt=True
            )
            prompt_len = len(tokenizer(rendered, add_special_tokens=False).input_ids)
            answer_len = len(
                tokenizer(messages[2]["content"] + tokenizer.eos_token, add_special_tokens=False).input_ids
            )
            prompts.append(prompt_len)
            answers.append(answer_len)
            totals.append(prompt_len + answer_len)

        print("\n=== %s（%d 条）===" % (name, len(rows)))
        for label, values in (("prompt", prompts), ("answer", answers), ("合计", totals)):
            print(
                "  %-8s 最小 %4d  中位 %4d  p90 %4d  最大 %4d"
                % (label, min(values), pct(values, 0.5), pct(values, 0.9), max(values))
            )

        need = pct(totals, 0.95)
        print("  建议 max_len：>= %d（覆盖 95%% 样本）" % need)
        if max(totals) > 1024:
            print("  ⚠️ 有样本超过 1024 token，当前 max_len=1024 会截掉回答")
        dropped = sum(1 for p, a, t in zip(prompts, answers, totals) if p >= 1024)
        print("  prompt 单独超过 1024 的样本：%d 条" % dropped)


if __name__ == "__main__":
    main()
