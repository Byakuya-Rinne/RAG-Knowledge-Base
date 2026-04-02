import asyncio
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI()
app.add_middleware(
    CORSMiddleware,  # 启用跨域中间件
    allow_origins=["*"],  # 允许所有来源（任何网页都能调用）
    allow_methods=["*"],  # 允许所有请求方式（GET/POST等）
    allow_headers=["*"],  # 允许所有请求头
)

@app.get("/sample_stream")
async def sample_stream():
    async def event():
        for i in range(4):
            yield f"data:{i + 1}\n\n"
            await asyncio.sleep(1)
        yield f"data:[END]\n\n"

    return StreamingResponse(
        event(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲
            "Content-Encoding": "identity",  # 避免 gzip 压缩导致的等待
        }
    )

if __name__ == '__main__':
    uvicorn.run(app, host="127.0.0.1", port=8001)








