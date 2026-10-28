"""Qwen2.5-1.5B-Instruct LoRA 微调（单卡 8GB 可跑）。

## 关键设计

**① 只对 assistant 部分算 loss**
把「system + user」的 token 全部置为 -100，只对回复部分回传梯度。
否则模型会把大量精力学"怎么复述老人的问题"，而不是"怎么回答"。

**② 显存按 8GB 调**
  · bf16（RTX 4060 是 Ada，原生支持，不用 fp16 省显存换稳定性）
  · batch 1 + 梯度累积 8（等效 batch 8，但显存只占 1 份）
  · 开 gradient_checkpointing（用时间换显存）
  · max_len 1024（我们的样本 40–120 字回复，1024 足够）

**③ LoRA 只训 attn + mlp 的线性层**
r=16 已经够表达"说话方式"这种风格偏移；r 太大会过拟合到具体句子。

用法：
    python scripts/train_lora.py
    python scripts/train_lora.py --epochs 3 --lr 2e-4
输出：
    out/lora-bilin/            （adapter + tokenizer）
    out/train_log.json
"""

from __future__ import annotations

import argparse
import json
import os
import random
from pathlib import Path

# 显存碎片优化：上一轮峰值 7.9GB / 8.19GB 已经贴顶，
# 不处理碎片的话，同样的配置偶尔就会 OOM（本轮就撞上了）。
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import torch
from datasets import Dataset
from peft import LoraConfig, TaskType, get_peft_model
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    DataCollatorForSeq2Seq,
    Trainer,
    TrainingArguments,
)

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "final"
DEFAULT_MODEL = ROOT / "models" / "Qwen2.5-1.5B-Instruct"
OUT = ROOT / "out" / "lora-bilin"

TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]


def build_example(messages: list[dict], tokenizer, max_len: int) -> dict:
    """把一条样本转成 input_ids / labels（只在回复部分算 loss）。

    ⚠️ 踩过的坑（transformers v5）：`apply_chat_template(..., tokenize=True)`
    返回的是 **BatchEncoding**（一个 dict，含 input_ids / attention_mask），
    不是 list。直接拿它 `+` 列表会 TypeError，而 `len()` 得到的是**键的数量 2**
    —— 看起来像"提示词只有 2 个 token"，非常容易误判成模板坏了。
    所以这里统一走 `tokenize=False` 再自己编码，v4/v5 都能用。
    """
    prompt = messages[:2]
    answer = messages[2]["content"]

    rendered = tokenizer.apply_chat_template(
        prompt, tokenize=False, add_generation_prompt=True
    )
    prompt_ids = tokenizer(rendered, add_special_tokens=False).input_ids
    answer_ids = tokenizer(
        answer + tokenizer.eos_token, add_special_tokens=False
    ).input_ids

    input_ids = (prompt_ids + answer_ids)[:max_len]
    labels = ([-100] * len(prompt_ids) + answer_ids)[:max_len]

    # 全被截掉就返回空，交给上层过滤
    if all(label == -100 for label in labels):
        return {"input_ids": [], "labels": []}
    return {"input_ids": input_ids, "labels": labels}


def load_rows(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=str(DEFAULT_MODEL))
    parser.add_argument("--epochs", type=float, default=3.0)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--batch", type=int, default=1)
    parser.add_argument("--grad-accum", type=int, default=8)
    # 实测 token 分布：合计最大 1271、p90 1193。
    # 1216 能覆盖约 97% 且留出显存余量（1280 时峰值爆过）。
    parser.add_argument("--max-len", type=int, default=1216)
    parser.add_argument("--lora-r", type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=32)
    parser.add_argument("--seed", type=int, default=20261018)
    args = parser.parse_args()

    random.seed(args.seed)
    torch.manual_seed(args.seed)

    print("  torch %s | CUDA %s" % (torch.__version__, torch.cuda.is_available()))
    if torch.cuda.is_available():
        props = torch.cuda.get_device_properties(0)
        print("  GPU %s | %.1f GB" % (props.name, props.total_memory / 1024**3))
    print("  模型 %s" % args.model)
    if args.max_len < 1200:
        print("  ⚠️ max_len=%d 偏小：实测 prompt p90 已有 1130 token" % args.max_len)

    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # 只加载需要的，避免不必要的显存
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
        device_map="auto" if torch.cuda.is_available() else None,
        trust_remote_code=True,
    )
    model.config.use_cache = False

    lora = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=0.05,
        target_modules=TARGET_MODULES,
        bias="none",
    )
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    # 数据
    train_rows = load_rows(DATA / "train.jsonl")
    print("  训练样本 %d 条" % len(train_rows))
    encoded = []
    for row in train_rows:
        item = build_example(row["messages"], tokenizer, args.max_len)
        if item["input_ids"]:
            encoded.append(item)
    dropped = len(train_rows) - len(encoded)
    print("  可用样本 %d 条（因超长丢弃 %d 条）" % (len(encoded), dropped))
    if dropped:
        print("  ⚠️ 有 %d 条被丢弃：产品提示词本身约 1000 token，" % dropped)
        print("     若 max_len 设小了，回答会被整段截掉（labels 全 -100）。建议 --max-len 1280")
    if not encoded:
        raise SystemExit("没有可用样本，检查 max_len 与数据")
    dataset = Dataset.from_list(encoded)

    collator = DataCollatorForSeq2Seq(
        tokenizer=tokenizer,
        model=None,
        padding=True,
        pad_to_multiple_of=8,
        label_pad_token_id=-100,
    )

    OUT.mkdir(parents=True, exist_ok=True)

    # transformers v5 移除了 warmup_ratio（只保留 warmup_steps），
    # 所以自己按比例算步数。总步数 = ceil(样本 / (batch × 累积)) × epoch。
    steps_per_epoch = -(-len(encoded) // max(1, args.batch * args.grad_accum))
    total_steps = max(1, int(steps_per_epoch * args.epochs))
    warmup_steps = max(1, int(total_steps * 0.05))
    print("  总步数 %d（每 epoch %d 步），warmup %d 步" % (total_steps, steps_per_epoch, warmup_steps))

    training_args = TrainingArguments(
        output_dir=str(OUT),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        lr_scheduler_type="cosine",
        # ⚠️ v5 没有 warmup_ratio
        warmup_steps=warmup_steps,
        logging_steps=1,
        save_strategy="epoch",
        save_total_limit=2,
        bf16=torch.cuda.is_available(),
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        optim="adamw_torch",
        report_to=[],
        dataloader_num_workers=0,   # Windows 上多进程数据加载容易出问题
        seed=args.seed,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        data_collator=collator,
    )

    print("\n  开始训练 ...")
    result = trainer.train()

    model.save_pretrained(str(OUT))
    tokenizer.save_pretrained(str(OUT))
    print("  adapter 已保存：%s" % OUT)

    log = {
        "model": str(args.model),
        "samples": len(encoded),
        "epochs": args.epochs,
        "lr": args.lr,
        "batch": args.batch,
        "grad_accum": args.grad_accum,
        "lora_r": args.lora_r,
        "train_loss": getattr(result, "training_loss", None),
        "metrics": getattr(result, "metrics", {}),
    }
    (ROOT / "out" / "train_log.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print("  train_loss = %.4f" % (log["train_loss"] or 0))


if __name__ == "__main__":
    main()
