import asyncio
from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pandas import bdate_range

# 1. 初始化+跨域（最基础配置）
app = FastAPI()
app.add_middleware(
    CORSMiddleware,        # 启用跨域中间件
    allow_origins=["*"],   # 允许所有来源（任何网页都能调用）
    allow_methods=["*"],   # 允许所有请求方式（GET/POST等）
    allow_headers=["*"],   # 允许所有请求头
)

task_queues = {}

async def long_task(session_id: str):
    queue = asyncio.Queue()
    task_queues[session_id] = queue

    for i in range(4):
        msg = f"{session_id}的循环结果{i}"
        await queue.put(msg)
        await asyncio.sleep(0.8)

    await queue.put(None) # 队列的None是结束标签

# 提交
@app.get("/submit/{session_id}")
async def submit_task(session_id: str, background_tasks: BackgroundTasks):
    background_tasks.add_task(long_task, session_id)
    return {"message": "任务已启动", "session_id": session_id}

@app.get("/stream/{session_id}")
async def stream_result(session_id: str):
    async def event_generator():
        while session_id not in task_queues:
            await asyncio.sleep(0.2)

        queue = task_queues[session_id]
        while True:
            msg = await queue.get()
            if msg is None:
                break
            yield f"data: {msg}\n\n"

    return StreamingResponse( event_generator(), media_type="text/event-stream")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8001)