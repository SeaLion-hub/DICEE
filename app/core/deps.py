"""FastAPI 의존성. HTTP 클라이언트 등 앱 생명주기 객체 주입."""

from fastapi import Request

import httpx


def get_httpx_client(request: Request) -> httpx.AsyncClient:
    """
    앱 lifespan에서 생성한 싱글톤 AsyncClient 반환.
    매 요청마다 새 클라이언트를 만들지 않아 소켓 고갈(TIME_WAIT) 방지.
    """
    return request.app.state.httpx_client
