"""로컬 실행 스크립트. Windows에서 psycopg/asyncpg 호환을 위해 이벤트 루프 정책을 먼저 설정."""
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )
