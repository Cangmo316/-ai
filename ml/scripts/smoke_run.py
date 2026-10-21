"""端到端冒烟：加载模型 → 生成一句 → 检查显存。不训练。

## 为什么要做这一步

"环境装好了"和"能跑通"是两件事。这一步验证：
  · 模型文件完整（safetensors 能加载，不会报 missing keys）
  · tokenizer 的 chat template 可用（训练与推理都依赖它）
  · 1.5B bf16 在 8GB 显存上装得下（这是能不能训练的前提）
  · 生成不再卡住（能吐字）

跑完记下显存占用，据此决定训练时的 batch 与序列长度。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "models" / "Qwen2.5-1.5B-Instruct"
DATA = ROOT / "data" / "final"

print("=== 1. 加载 tokenizer ===")
tokenizer = AutoTokenizer.from_pretrained(str(BASE), trust_remote_code=True)
print("  vocab %d | pad %s | eos %s" % (
    tokenizer.vocab_size, tokenizer.pad_token, tokenizer.eos_token))
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token

print("\n=== 2. chat template 检查 ===")
sample = [{"role": "user", "content": "你好"}]
rendered = tokenizer.apply_chat_template(sample, tokenize=False, add_generation_prompt=True)
print("  渲染结果（前 60 字）: %r" % rendered[:60])

print("\n=== 3. 取一条真实训练样本，验证 mask 逻辑 ===")
rows = [json.loads(line) for line in (DATA / "train.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
row = rows[0]
# v5 的 tokenize=True 返回 BatchEncoding，必须走 tokenize=False 再编码
rendered_prompt = tokenizer.apply_chat_template(row["messages"][:2], tokenize=False, add_generation_prompt=True)
prompt_ids = tokenizer(rendered_prompt, add_special_tokens=False).input_ids
answer_ids = tokenizer(row["messages"][2]["content"] + tokenizer.eos_token, add_special_tokens=False).input_ids
labels = [-100] * len(prompt_ids) + answer_ids
print("  prompt tokens %d | answer tokens %d | 参与 loss 的 token %d" % (
    len(prompt_ids), len(answer_ids), sum(1 for x in labels if x != -100)))
assert len(prompt_ids) > 5, "提示词只有 %d 个 token，chat template 可能没生效" % len(prompt_ids)
assert len(answer_ids) > 5, "回复只有 %d 个 token" % len(answer_ids)

print("\n=== 4. 加载模型到 GPU（bf16）===")
started = time.time()
model = AutoModelForCausalLM.from_pretrained(
    str(BASE),
    dtype=torch.bfloat16,
    device_map="auto",
    trust_remote_code=True,
)
model.eval()
print("  加载耗时 %.1f 秒" % (time.time() - started))
allocated = torch.cuda.memory_allocated() / 1024**3
reserved = torch.cuda.memory_reserved() / 1024**3
print("  权重占用 %.2f GB | 已保留 %.2f GB" % (allocated, reserved))

print("\n=== 5. 生成一句（验证能吐字）===")
messages = [
    {"role": "system", "content": "你叫比邻AI，陪老人说话。短句、口语、用您，不用句号收尾。"},
    {"role": "user", "content": "今天天气不错，我出去走了走"},
]
prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
started = time.time()
with torch.no_grad():
    out = model.generate(
        **inputs, max_new_tokens=120, do_sample=True, temperature=0.8,
        top_p=0.9, pad_token_id=tokenizer.pad_token_id,
    )
elapsed = time.time() - started
new_tokens = out.shape[1] - inputs["input_ids"].shape[1]
text = tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
print("  生成 %d tokens / %.1f 秒 → %.1f tok/s" % (new_tokens, elapsed, new_tokens / max(elapsed, 0.01)))
print("  回复: %r" % text.strip())

peak = torch.cuda.max_memory_allocated() / 1024**3
print("\n=== 6. 显存结论 ===")
print("  峰值 %.2f GB / 总 8.00 GB" % peak)
headroom = 8.0 - peak
print("  余量 %.2f GB → 训练时 %s" % (
    headroom,
    "可用 batch 1 + 梯度累积 + gradient checkpointing（1.5B 方案可行）" if headroom > 2.5
    else "余量偏紧，建议换 0.5B 或缩短 max_len",
))

del model
torch.cuda.empty_cache()
print("\n=== 冒烟通过 ===")
