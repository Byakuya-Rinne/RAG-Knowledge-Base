import asyncio
from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel


app = FastAPI()
app.add_middleware(
    CORSMiddleware,        # 启用跨域中间件
    allow_origins=["*"],   # 允许所有来源（任何网页都能调用）
    allow_methods=["*"],   # 允许所有请求方式（GET/POST等）
    allow_headers=["*"],   # 允许所有请求头
)

task_queues = {}

class QueryRequest(BaseModel):
    query: str
    session_id: str



@app.post("/submit_query")
async def submit_query(req: QueryRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(long_task, req.query, req.session_id)
    return {"message": "任务已启动", "session_id": req.session_id}




async def long_task(session_id: str, query: str):
    queue = asyncio.Queue()
    task_queues[session_id] = queue

    for i in range(4):
        msg = f"【{query}】的第{i+1}段回答：xxx{i+1}"
        await asyncio.sleep(1)
        await queue.put(msg)
    await queue.put(None)



@app.get("/stream/{session_id}")
async def stream_result(session_id: str):
    async def getter():
        while session_id not in task_queues:
            await asyncio.sleep(0.2)
        # task_queues[session_id]已经有东西了
        queue = task_queues[session_id]

        while True:
            msg = await queue.get()
            yield f"data: {msg}\n\n"
            # task_queues[session_id]取完了
            if msg is None:
                break

    return StreamingResponse(getter(), media_type="text/event-stream")



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)





