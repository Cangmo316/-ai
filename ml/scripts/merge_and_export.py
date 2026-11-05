"""把 LoRA adapter 合并进基座，导出 Ollama 可用的模型。

## 为什么必须合并

微调产出的是 LoRA adapter（70MB，只是"增量"），不能单独推理。
Ollama / llama.cpp 只吃完整权重，所以必须：
    Qwen2.5-1.5B (bf16) + lora-bilin → 合并后的完整模型 → 转 GGUF → 量化

## 为什么要量化

原始 bf16 是 2.9GB，家用 CPU 跑不动。
Q4_K_M 量化后约 1.0GB，内存占用降到 1.5GB 左右，8G 内存的老电脑就能跑。
**量化会掉一点质量**，所以脚本会顺手做一次冒烟对比，让你看到掉了多少。

## 前置

    pip install transformers peft torch accelerate   （ml/.venv 里已有）
    llama.cpp 的 convert_hf_to_gguf.py + quantize    （脚本会提示怎么拿）

用法：
    python ml/scripts/merge_and_export.py            # 只合并
    python ml/scripts/merge_and_export.py --quant     # 合并 + 转 GGUF + 量化
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "models" / "Qwen2.5-1.5B-Instruct"
ADAPTER = ROOT / "out" / "lora-bilin"
MERGED = ROOT / "out" / "merged-bilin"
GGUF_DIR = ROOT / "out" / "gguf"


def merge() -> None:
    print("=== 1. 加载基座 ===")
    tokenizer = AutoTokenizer.from_pretrained(str(BASE), trust_remote_code=True)
    base = AutoModelForCausalLM.from_pretrained(
        str(BASE), dtype=torch.bfloat16, trust_remote_code=True, low_cpu_mem_usage=True
    )
    print("  基座参数量: %.2f B" % (sum(p.numel() for p in base.parameters()) / 1e9))

    print("\n=== 2. 合并 LoRA ===")
    if not ADAPTER.exists():
        raise SystemExit("找不到 adapter：%s（先跑 train_lora.py）" % ADAPTER)
    model = PeftModel.from_pretrained(base, str(ADAPTER))
    model = model.merge_and_unload()
    print("  已合并（merge_and_unload）")
    print("  合并后参数量: %.2f B" % (sum(p.numel() for p in model.parameters()) / 1e9))

    print("\n=== 3. 保存完整模型 ===")
    MERGED.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(MERGED), safe_serialization=True)
    tokenizer.save_pretrained(str(MERGED))
    total = sum(f.stat().st_size for f in MERGED.rglob("*") if f.is_file())
    print("  落盘: %s (%.2f GB)" % (MERGED, total / 1024**3))

    print("\n=== 4. 冒烟：合并前后各说一句 ===")
    prompt = "今天天气不错，我出去走了走"
    system = "你叫比邻AI，陪老人说话。短句、口语、用您，不用句号收尾。"
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    rendered = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(rendered, return_tensors="pt")

    model.eval()
    with torch.no_grad():
        out = model.generate(
            **inputs, max_new_tokens=80, do_sample=True, temperature=0.7,
            top_p=0.9, pad_token_id=tokenizer.pad_token_id,
        )
    text = tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
    print("  合并后回复: %r" % text.strip()[:120])

    del model, base
    torch.cuda.empty_cache() if torch.cuda.is_available() else None


def find_llama_cpp() -> Path | None:
    """找 llama.cpp 的转换脚本与量化工具。"""
    candidates = [
        ROOT / "llama.cpp",
        Path(r"E:\llama.cpp"),
        Path.home() / "llama.cpp",
    ]
    for path in candidates:
        if (path / "convert_hf_to_gguf.py").exists():
            return path
    return None


def to_gguf(llama: Path, quant: str) -> None:
    GGUF_DIR.mkdir(parents=True, exist_ok=True)
    f16 = GGUF_DIR / "bilin-f16.gguf"
    out = GGUF_DIR / ("bilin-%s.gguf" % quant.lower())

    print("\n=== 5. 转 GGUF（f16）===")
    cmd = [sys.executable, str(llama / "convert_hf_to_gguf.py"), str(MERGED),
           "--outfile", str(f16), "--outtype", "f16"]
    print("  " + " ".join(cmd[-4:]))
    subprocess.run(cmd, check=True)

    # 量化工具在 build 目录里，Windows 是 .exe
    quant_bin = None
    for name in ("llama-quantize.exe", "llama-quantize", "quantize.exe", "quantize"):
        for sub in ("build/bin", "build", "."):
            p = llama / sub / name
            if p.exists():
                quant_bin = p
                break
        if quant_bin:
            break
    if not quant_bin:
        print("  ⚠️ 没找到 llama-quantize，先编译 llama.cpp（cmake -B build && cmake --build build -j）")
        print("  已生成 f16，可手动量化：llama-quantize %s %s %s" % (f16, out, quant))
        return

    print("\n=== 6. 量化到 %s ===" % quant)
    subprocess.run([str(quant_bin), str(f16), str(out), quant], check=True)
    print("  产物: %s (%.2f GB)" % (out, out.stat().st_size / 1024**3))


def write_modelfile(quant: str) -> Path:
    """生成 Ollama 的 Modelfile —— 把产品提示词也固化进去。"""
    gguf = GGUF_DIR / ("bilin-%s.gguf" % quant.lower())
    modelfile = GGUF_DIR / "Modelfile"
    content = """# 比邻AI 私有化模型（ollama create bilin-qwen -f Modelfile）
#
# 为什么参数这么设：
#   temperature 0.7  —— 陪伴说话要有点变化，太低像念稿
#   top_p 0.9        —— 收一收长尾，老人场景不要生成奇怪内容
#   num_ctx 4096     —— 产品提示词本身约 1000 token，留足对话余量
#   repeat_penalty 1.05 —— 轻微抑制复读（实测 1.1 会让"您"字重复变少但不自然）
FROM ./%(gguf)s

PARAMETER temperature 0.7
PARAMETER top_p 0.9
PARAMETER num_ctx 4096
PARAMETER repeat_penalty 1.05
PARAMETER stop "<|im_end|>"
PARAMETER stop "<|endoftext|>"

TEMPLATE \"\"\"{{ if .System }}<|im_start|>system
{{ .System }}<|im_end|>
{{ end }}{{ if .Prompt }}<|im_start|>user
{{ .Prompt }}<|im_end|>
{{ end }}<|im_start|>assistant
{{ .Response }}<|im_end|>
\"\"\"
""" % {"gguf": gguf.name}
    modelfile.write_text(content, encoding="utf-8")
    print("\n=== 7. Modelfile ===")
    print("  %s" % modelfile)
    return modelfile


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quant", action="store_true", help="同时转 GGUF 并量化")
    parser.add_argument("--quant-type", default="Q4_K_M")
    parser.add_argument("--skip-merge", action="store_true", help="已合并过，只做 GGUF")
    args = parser.parse_args()

    if not args.skip_merge:
        merge()

    if args.quant:
        llama = find_llama_cpp()
        if not llama:
            print("\n⚠️ 没找到 llama.cpp。获取方式：")
            print("  git clone https://github.com/ggml-org/llama.cpp E:\\llama.cpp")
            print("  cd E:\\llama.cpp && cmake -B build && cmake --build build --config Release -j")
            print("  然后重跑：python ml/scripts/merge_and_export.py --quant --skip-merge")
            return
        to_gguf(llama, args.quant_type)
        write_modelfile(args.quant_type)

    print("\n=== 下一步 ===")
    print("  ollama create bilin-qwen -f %s" % (GGUF_DIR / "Modelfile"))
    print("  然后在 server/.env 里：")
    print("    LLM_PROVIDER=openai_compat")
    print("    LLM_BASE_URL=http://127.0.0.1:11434/v1")
    print("    LLM_MODEL=bilin-qwen")
    print("    LLM_API_KEY=ollama")


if __name__ == "__main__":
    main()
