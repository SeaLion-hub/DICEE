# 크롤러 아웃바운드 HTTP 프록시 (DI 계약)

Crawlee의 `ProxyConfiguration`처럼 **프록시는 비즈니스 로직 밖**에서 주입한다. DICEE는 URL만 제공하고, 실제 `requests`/`httpx` 호출부에서 `proxies=`에 넘긴다.

## 우선순위

1. 설정 `crawler_http_proxy_url` (Pydantic `SecretStr`; Railway 등에서는 보통 `CRAWLER_HTTP_PROXY_URL`).
2. 환경 변수 `CRAWLER_HTTP_PROXY` (표준 관례; 1이 비어 있을 때 `get_crawler_http_proxy_url` 폴백).

둘 다 비어 있으면 프록시 없음.

## 코드

- 헬퍼: [app/core/crawl_worker_proxy.py](../app/core/crawl_worker_proxy.py) — `get_crawler_http_proxy_url()`, `crawler_requests_proxies()`.

## 크롤러 모듈에서 사용 예

```python
from app.core.crawl_worker_proxy import crawler_requests_proxies

proxies = crawler_requests_proxies()
resp = requests.get(url, timeout=30, proxies=proxies)
```

외부 패키지(SeaLion-hub/crawler)는 동일 환경 변수만 읽어도 되고, DICEE에 임베드된 모듈은 헬퍼 사용을 권장한다.

## 보안

프록시 URL에 자격 증명이 포함될 수 있으므로 로그에 출력하지 않는다.
