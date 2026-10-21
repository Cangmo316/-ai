"""训练脚本干跑：验证数据编码、LoRA 挂载、单步前向+反向，但不做完整训练。

## 为什么值得单独跑一遍

完整训练要十几分钟。如果第 3 步才报错（比如 collator 不认 labels、LoRA 挂错层、
显存不够），前面全白等。这一步在 1 分钟内把训练会碰到的环节都摸一遍：

  1. 数据编码（含截断）
  2. LoRA 挂载（可训练参数占比）
  3. 真实 batch 的前向 + 反向（loss 能不能算出来）
  4. 显存峰值（据此确认 batch/seq 设置安全）

任一步失败就说明训练会失败，不必真跑。
"""

from __future__ import annotations

import json
from pathlib import Path

import torch
from peft import LoraConfig, TaskType, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer, DataCollatorForSeq2Seq

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "models" / "Qwen2.5-1.5B-Instruct"
DATA = ROOT / "data" / "final"
MAX_LEN = 1280
TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]


def build_example(messages, tokenizer, max_len):
    rendered = tokenizer.apply_chat_template(messages[:2], tokenize=False, add_generation_prompt=True)
    prompt_ids = tokenizer(rendered, add_special_tokens=False).input_ids
    answer_ids = tokenizer(messages[2]["content"] + tokenizer.eos_token, add_special_tokens=False).input_ids
    input_ids = (prompt_ids + answer_ids)[:max_len]
    labels = ([-100] * len(prompt_ids) + answer_ids)[:max_len]
    if all(label == -100 for label in labels):
        return None
    return {"input_ids": input_ids, "labels": labels}


def main() -> None:
    print("=== 1. tokenizer + 数据编码 ===")
    tokenizer = AutoTokenizer.from_pretrained(str(BASE), trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    rows = [json.loads(line) for line in (DATA / "train.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    encoded, dropped = [], 0
    for row in rows:
        item = build_example(row["messages"], tokenizer, MAX_LEN)
        if item:
            encoded.append(item)
        else:
            dropped += 1
    print("  样本 %d 条 → 可用 %d 条，丢弃 %d 条（max_len=%d）" % (len(rows), len(encoded), dropped, MAX_LEN))
    lengths = [len(e["input_ids"]) for e in encoded]
    print("  token 长度 最小 %d / 中位 %d / 最大 %d" % (min(lengths), sorted(lengths)[len(lengths)//2], max(lengths)))

    print("\n=== 2. 加载模型 + 挂 LoRA ===")
    model = AutoModelForCausalLM.from_pretrained(
        str(BASE), dtype=torch.bfloat16, device_map="auto", trust_remote_code=True
    )
    model.config.use_cache = False
    # 必须开：1.5B 在 1000+ token 上不 checkpointing 的话，激活就吃掉 7GB+
    # （干跑第一次就是这里 OOM 的，训练脚本里是由 TrainingArguments 自动开的）
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()   # 配合 checkpointing，否则 LoRA 梯度断掉
    lora = LoraConfig(
        task_type=TaskType.CAUSAL_LM, r=16, lora_alpha=32, lora_dropout=0.05,
        target_modules=TARGETS, bias="none",
    )
    model = get_peft_model(model, lora)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print("  可训练参数 %s / 总 %s（%.2f%%）" % (
        f"{trainable:,}", f"{total:,}", 100.0 * trainable / total))

    print("\n=== 3. 真实 batch 前向 + 反向 ===")
    collator = DataCollatorForSeq2Seq(
        tokenizer=tokenizer, model=None, padding=True, pad_to_multiple_of=8, label_pad_token_id=-100
    )
    batch = collator([encoded[0]])   # batch 1：8GB 卡上更稳
    device = next(model.parameters()).device
    batch = {k: v.to(device) for k, v in batch.items()}
    print("  batch shapes: input_ids %s, labels %s" % (tuple(batch["input_ids"].shape), tuple(batch["labels"].shape)))

    model.train()
    out = model(**batch)
    loss = out.loss
    print("  forward loss = %.4f" % loss.item())
    loss.backward()
    grad_norm = sum(
        p.grad.detach().float().norm().item() for p in model.parameters() if p.grad is not None
    )
    print("  反向传播成功，梯度范数 %.4f" % grad_norm)

    peak = torch.cuda.max_memory_allocated() / 1024**3
    print("\n=== 4. 显存 ===")
    print("  峰值 %.2f GB / 8.00 GB（batch=1, seq=%d）" % (peak, MAX_LEN))
    print("  余量 %.2f GB" % (8.0 - peak))

    print("\n=== 干跑通过：训练可以启动 ===")
    del model
    torch.cuda.empty_cache()


if __name__ == "__main__":
    main()
