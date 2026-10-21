"""环境冒烟测试：不训练，只验证训练脚本用到的 API 在当前版本可用。

## 为什么需要

装完发现 transformers 是 **5.20.2**（v5 大版本）。v5 改了不少接口：
  · `TrainingArguments` 的重命名（如 `evaluation_strategy` → `eval_strategy`）
  · `DataCollatorForSeq2Seq` 的归属模块
  · `Trainer` 的 `tokenizer` 参数 → `processing_class`

这些不提前验，等到训练跑了 10 分钟才报 TypeError 就白等了。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "final"
BASE = ROOT / "models" / "Qwen2.5-1.5B-Instruct"

print("  python", sys.version.split()[0])

import torch  # noqa: E402

print("  torch", torch.__version__, "| CUDA", torch.cuda.is_available())
if torch.cuda.is_available():
    print("  GPU  ", torch.cuda.get_device_name(0))

import transformers  # noqa: E402
import peft  # noqa: E402
import datasets  # noqa: E402
import accelerate  # noqa: E402

print("  transformers", transformers.__version__)
print("  peft        ", peft.__version__)
print("  datasets    ", datasets.__version__)
print("  accelerate  ", accelerate.__version__)

print("\n=== 关键 API 检查 ===")
ok = True

from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: E402

print("  AutoModelForCausalLM  OK")

Trainer = None
TrainingArguments = None
for module_name in ("transformers",):
    module = sys.modules[module_name]
    Trainer = getattr(module, "Trainer", None)
    TrainingArguments = getattr(module, "TrainingArguments", None)
print("  Trainer               %s" % ("OK" if Trainer else "缺失"))
print("  TrainingArguments     %s" % ("OK" if TrainingArguments else "缺失"))
ok = ok and bool(Trainer) and bool(TrainingArguments)

# DataCollatorForSeq2Seq 在 v4 里在 transformers 顶层，v5 可能搬家
collator_cls = None
try:
    from transformers import DataCollatorForSeq2Seq as collator_cls  # noqa: N813
    print("  DataCollatorForSeq2Seq  OK（transformers 顶层）")
except Exception:
    try:
        from transformers.data.data_collator import DataCollatorForSeq2Seq as collator_cls  # type: ignore
        print("  DataCollatorForSeq2Seq  OK（transformers.data.data_collator）")
    except Exception as exc:  # noqa: BLE001
        print("  DataCollatorForSeq2Seq  缺失：%s" % exc)
        ok = False

# DataCollatorForCompletionOnlyLM 是更合适的工具（只对回复算 loss），看有没有
try:
    from transformers import DataCollatorForCompletionOnlyLM  # noqa: F401
    print("  DataCollatorForCompletionOnlyLM  可用（可选）")
except Exception:
    print("  DataCollatorForCompletionOnlyLM  不可用（我们用自定义 mask，不影响）")

from peft import LoraConfig, TaskType, get_peft_model  # noqa: E402

print("  LoraConfig / get_peft_model  OK")

print("\n=== TrainingArguments 参数检查 ===")
try:
    args = TrainingArguments(
        output_dir=str(ROOT / "out" / "_smoke"),
        num_train_epochs=1,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=8,
        learning_rate=2e-4,
        lr_scheduler_type="cosine",
        warmup_steps=5,   # v5 移除了 warmup_ratio
        logging_steps=1,
        save_strategy="epoch",
        bf16=True,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        optim="adamw_torch",
        report_to=[],
        dataloader_num_workers=0,
        seed=1,
    )
    print("  构造成功")
    # 看看它把关键字段存成了什么
    for key in ("bf16", "gradient_checkpointing", "optim", "save_strategy"):
        print("    %-24s %s" % (key, getattr(args, key, "(无此字段)")))
except Exception as exc:  # noqa: BLE001
    ok = False
    print("  构造失败：%s" % exc)

print("\n=== 数据检查 ===")
for name in ("train.jsonl", "eval.jsonl"):
    path = DATA / name
    if not path.exists():
        print("  %-12s 不存在" % name)
        ok = False
        continue
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    chars = sum(len(r["messages"][1]["content"]) + len(r["messages"][2]["content"]) for r in rows)
    print("  %-12s %3d 条 / %5d 字" % (name, len(rows), chars))

print("\n=== 模型文件检查 ===")
need = ("config.json", "tokenizer.json", "tokenizer_config.json", "vocab.json", "merges.txt", "model.safetensors")
for name in need:
    path = BASE / name
    size = path.stat().st_size / 1024 / 1024 if path.exists() else 0
    print("  %-24s %s %8.1f MB" % (name, "OK" if path.exists() else "缺", size))
    if not path.exists():
        ok = False

print("\n" + ("=== 冒烟测试通过 ===" if ok else "=== 有项目未通过，见上 ==="))
sys.exit(0 if ok else 1)
