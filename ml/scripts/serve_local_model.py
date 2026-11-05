"""本地推理服务：把合并后的模型包装成 OpenAI 兼容接口。

    python ml/scripts/serve_local_model.py --port 8100

## 为什么自己写一个而不用 Ollama / llama.cpp

本来计划用 Ollama 导入，但实测这台机器**下载不到任何 release 二进制**
（GitHub API 通，但 release 资产域名被拦，Ollama 官网也连不上）。
而 `ml/.venv` 里已经装好 torch + transformers，模型也已合并完毕 ——
直接用它们起一个 OpenAI 兼容端点，**不需要任何额外下载**。

产品侧（`app/llm/openai_compat.py`）本来就只要求"OpenAI 兼容"，
所以后端只要改 `.env` 指向这里，就完成了从 DeepSeek 到本地的切换。

## 性能预期（诚实说明）

CPU / 单卡 8G 上 1.5B bf16：
  · GPU（RTX 4060）：约 30–50 字/秒，体验接近可用
  · 纯 CPU：约 4–8 字/秒，老人等一句话要十几秒 —— 只适合演示或断网兜底

要更快就量化（Q4 约 3–4 倍），但那需要 llama.cpp 的量化工具，本机下不到，
所以这个服务**不做量化**，保持和训练时一致的 bf16。

## 接口

POST /v1/chat/completions  —— 支持 stream=true（SSE），与 OpenAI 同构
GET  /v1/models            —— 返回模型名，便于探活
GET  /healthz              —— 简单存活检查
"""

from __future__ import annotations

import argparse
import asyncio
import json
import threading
import time
from pathlib import Path
from typing import Any

import torch
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from transformers import AutoModelForCausalLM, AutoTokenizer, TextIteratorStreamer

ROOT = Path(__file__).resolve().parent.parent
MERGED = ROOT / "out" / "merged-bilin"
BASE = ROOT / "models" / "Qwen2.5-1.5B-Instruct"

STATE: dict[str, Any] = {}


def load(model_dir: Path) -> None:
    print("  加载模型：%s" % model_dir, flush=True)
    started = time.time()
    tokenizer = AutoTokenizer.from_pretrained(str(model_dir), trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        str(model_dir),
        dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
        device_map="auto" if torch.cuda.is_available() else None,
        trust_remote_code=True,
    )
    model.eval()
    STATE["tokenizer"] = tokenizer
    STATE["model"] = model
    print("  加载完成 %.1f 秒（%s）" % (
        time.time() - started,
        torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU",
    ), flush=True)


app = FastAPI(title="bilin-local-model")


class ChatRequest(BaseModel):
    model: str = "bilin-qwen"
    messages: list[dict] = []
    stream: bool = False
    temperature: float = 0.7
    top_p: float = 0.9
    max_tokens: int = 400


def render(messages: list[dict]) -> str:
    tokenizer = STATE["tokenizer"]
    return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)


def gen_kwargs(request: ChatRequest, inputs) -> dict:
    return dict(
        **inputs,
        max_new_tokens=max(1, min(request.max_tokens, 1024)),
        do_sample=request.temperature > 0,
        temperature=max(request.temperature, 0.01),
        top_p=request.top_p,
        repetition_penalty=1.05,
        pad_token_id=STATE["tokenizer"].pad_token_id,
    )


@app.get("/healthz")
def healthz():
    return {"ok": True, "service": "bilin-local-model", "model": MERGED.name}


@app.get("/v1/models")
def models():
    return {"object": "list", "data": [{"id": "bilin-qwen", "object": "model", "owned_by": "bilin"}]}


@app.post("/v1/chat/completions")
async def completions(request: ChatRequest):
    tokenizer = STATE["tokenizer"]
    model = STATE["model"]
    prompt = render(request.messages)
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    created = int(time.time())

    if not request.stream:
        with torch.no_grad():
            out = model.generate(**gen_kwargs(request, inputs))
        text = tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
        return JSONResponse({
            "id": "chatcmpl-local",
            "object": "chat.completion",
            "created": created,
            "model": request.model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": int(inputs["input_ids"].shape[1]),
                "completion_tokens": len(tokenizer(text, add_special_tokens=False).input_ids),
                "total_tokens": 0,
            },
        })

    async def stream():
        # TextIteratorStreamer + 后台线程：transformers 的 generate 是同步的，
        # 直接在里面 await 会堵死事件循环，SSE 就变成"最后一口气吐完"。
        streamer = TextIteratorStreamer(
            tokenizer, skip_prompt=True, skip_special_tokens=True, timeout=120.0
        )
        kwargs = gen_kwargs(request, inputs)
        kwargs["streamer"] = streamer
        error: dict[str, str] = {}

        def run():
            try:
                with torch.no_grad():
                    model.generate(**kwargs)
            except Exception as exc:  # noqa: BLE001
                error["message"] = str(exc)
            finally:
                # 生成结束（或异常）都要关掉，否则消费端会一直等
                streamer.end()

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

        # 首帧：让客户端立刻知道连上了（和 OpenAI 行为一致）
        first = {
            "id": "chatcmpl-local", "object": "chat.completion.chunk", "created": created,
            "model": request.model,
            "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
        }
        yield "data: " + json.dumps(first, ensure_ascii=False) + "\n\n"

        produced = False
        for piece in streamer:
            if not piece:
                continue
            produced = True
            chunk = {
                "id": "chatcmpl-local", "object": "chat.completion.chunk", "created": created,
                "model": request.model,
                "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}],
            }
            yield "data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n"

        if error:
            payload = {"error": {"message": error["message"], "type": "server_error"}}
            yield "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
        else:
            last = {
                "id": "chatcmpl-local", "object": "chat.completion.chunk", "created": created,
                "model": request.model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            yield "data: " + json.dumps(last, ensure_ascii=False) + "\n\n"
        yield "data: [DONE]\n\n"
        if not produced and not error:
            print("  ⚠️ 流式没有产出任何 token", flush=True)

    return StreamingResponse(stream(), media_type="text/event-stream")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=str(MERGED))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8100)
    args = parser.parse_args()

    model_dir = Path(args.model)
    if not model_dir.exists():
        raise SystemExit("找不到模型目录：%s（先跑 merge_and_export.py）" % model_dir)

    load(model_dir)
    print("  监听 http://%s:%d/v1  （OpenAI 兼容）" % (args.host, args.port), flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
