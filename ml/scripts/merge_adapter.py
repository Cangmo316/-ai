"""把 LoRA adapter 合并进基座，产出可部署的完整模型。

## 为什么必须做这一步

LoRA 训出来的只是一个 70MB 的 adapter，**不能直接对外提供服务**：
  · 大多数推理服务（Ollama / vLLM 的常规部署）要完整权重
  · 每次推理都要挂 adapter，多一层依赖，也更容易配错
  · 交付给别人时，一个 adapter 文件说明不了"这东西能跑"

合并后的目录才是"微调完成"的产物：一个自包含的 Qwen2.5-1.5B 变体。

## 为什么在 CPU 上合并

8GB 显存训练时已经很紧，合并要同时持有基座 + adapter + 输出，
放 GPU 容易 OOM。合并是纯权重运算，CPU 慢一点但稳。

用法：
    python scripts/merge_adapter.py
输出：
    out/bilin-qwen1.5b-merged/
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "models" / "Qwen2.5-1.5B-Instruct"
ADAPTER = ROOT / "out" / "lora-bilin"
MERGED = ROOT / "out" / "bilin-qwen1.5b-merged"


def main() -> None:
    if not ADAPTER.exists():
        raise SystemExit("找不到 adapter：%s" % ADAPTER)

    print("=== 1. 载入基座（CPU / bf16）===")
    started = time.time()
    base = AutoModelForCausalLM.from_pretrained(
        str(BASE), dtype=torch.bfloat16, device_map="cpu", trust_remote_code=True
    )
    tokenizer = AutoTokenizer.from_pretrained(str(BASE), trust_remote_code=True)
    print("  耗时 %.1f 秒" % (time.time() - started))

    print("\n=== 2. 挂 adapter 并合并 ===")
    model = PeftModel.from_pretrained(base, str(ADAPTER))
    model = model.merge_and_unload()
    print("  合并完成")

    print("\n=== 3. 保存到 %s ===" % MERGED)
    MERGED.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(MERGED), safe_serialization=True)
    tokenizer.save_pretrained(str(MERGED))

    total = sum(f.stat().st_size for f in MERGED.rglob("*") if f.is_file())
    files = [f.name for f in MERGED.iterdir() if f.is_file()]
    print("  文件 %d 个 / %.2f GB" % (len(files), total / 1024**3))
    for name in sorted(files):
        size = (MERGED / name).stat().st_size / 1024**2
        print("    %-34s %8.1f MB" % (name, size))

    print("\n=== 4. 用合并后的模型生成一句（验证可用）===")
    prompt = "你叫比邻AI，陪老人说话。短句、口语、用您，不用句号收尾。"
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": "我这两天心里有点闷，不想动弹"},
    ]
    rendered = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(rendered, return_tensors="pt")
    with torch.no_grad():
        out = model.generate(
            **inputs, max_new_tokens=120, do_sample=True, temperature=0.7,
            top_p=0.9, pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
        )
    text = tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
    print("  老人：我这两天心里有点闷，不想动弹")
    print("  回复：%s" % text.strip().replace("\n", " / "))

    info = {
        "base": str(BASE),
        "adapter": str(ADAPTER),
        "merged": str(MERGED),
        "size_gb": round(total / 1024**3, 2),
        "sample_reply": text.strip(),
    }
    (ROOT / "out" / "merge_log.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print("\n=== 合并完成：%s ===" % MERGED)


if __name__ == "__main__":
    main()
