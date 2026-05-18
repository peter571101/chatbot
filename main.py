import json
import os
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from openai import AsyncOpenAI

from context_injector import build_context, meal_prefix
from personas import list_personas, load_persona

load_dotenv()

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

app = FastAPI(title="人格蒸馏 · 对话")

BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    try:
        personas = list_personas()
        return templates.TemplateResponse(request, "index.html", {
            "personas": personas,
        })
    except Exception as e:
        import traceback
        return HTMLResponse(
            f"<pre>主页渲染失败:\n\n{traceback.format_exc()}</pre>",
            status_code=500,
        )


@app.get("/api/personas")
async def get_personas():
    return list_personas()


@app.post("/api/chat")
async def chat(request: Request):
    body = await request.json()
    persona_id = body.get("persona_id")
    message = body.get("message", "").strip()
    history = body.get("history", [])
    api_key = body.get("api_key") or os.getenv("DEEPSEEK_API_KEY")

    if not api_key:
        return StreamingResponse(
            iter(["data: " + json.dumps({"error": "请先设置 DeepSeek API Key"}, ensure_ascii=False) + "\n\n"]),
            media_type="text/event-stream",
        )

    persona = load_persona(persona_id)
    if not persona:
        return StreamingResponse(
            iter(["data: " + json.dumps({"error": f"未找到人格: {persona_id}"}, ensure_ascii=False) + "\n\n"]),
            media_type="text/event-stream",
        )

    # 组装消息。注入上下文的 persona：system 消息顺序为 context → persona
    #                               普通 persona：只有 persona system_prompt
    messages = []
    location = persona.get("location")
    needs_ctx = persona.get("needs_context") or location

    if needs_ctx:
        # 上下文放第一个 system 消息，优先级最高
        context_text = await build_context(location=location or "北京")
        messages.append({"role": "system", "content": context_text})

    messages.append({"role": "system", "content": persona["system_prompt"]})
    messages += [{"role": m["role"], "content": m["content"]} for m in history]

    # 防幻觉核心：把时段指令拼到 user 消息前面，AI 无法跳过
    if needs_ctx:
        prefix = meal_prefix(datetime.now().hour)
        message = f"{prefix}\n{message}"

    messages.append({"role": "user", "content": message})

    async def stream():
        try:
            client = AsyncOpenAI(
                api_key=api_key,
                base_url=DEEPSEEK_BASE_URL,
                http_client=httpx.AsyncClient(),
            )
            stream_ctx = await client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=messages,
                max_tokens=2048,
                stream=True,
            )
            async for chunk in stream_ctx:
                delta = chunk.choices[0].delta
                if delta.content:
                    yield "data: " + json.dumps({"text": delta.content}, ensure_ascii=False) + "\n\n"
            yield "data: " + json.dumps({"done": True}, ensure_ascii=False) + "\n\n"
        except Exception as e:
            yield "data: " + json.dumps({"error": str(e)}, ensure_ascii=False) + "\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="127.0.0.1", port=port)
