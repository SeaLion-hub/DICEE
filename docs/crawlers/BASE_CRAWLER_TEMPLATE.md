# New College Crawler Template (`BaseCrawler`)

Use this template for new crawler modules under `app/services/crawlers/`.

```python
from bs4 import BeautifulSoup, Tag

from app.services.crawlers.base import BaseCrawler, LinkItem, ScrapeResult


class ExampleCollegeCrawler(BaseCrawler):
    college_code = "example_college"
    display_name = "Example College"
    start_urls = ("https://example.edu/notice",)

    # Optional overrides
    list_timeout_seconds = 10.0
    detail_timeout_seconds = 10.0
    list_encoding = "utf-8"
    detail_encoding = "utf-8"
    # list_request_meta = {"retry_403": True}

    def parse_links(self, html: str, list_url: str) -> list[LinkItem]:
        soup = BeautifulSoup(html, "html.parser")
        links: list[LinkItem] = []
        for a in soup.select("a.notice-link"):
            if not isinstance(a, Tag):
                continue
            href = a.get("href")
            if isinstance(href, str) and href:
                links.append({"url": href})
        return links

    def parse_detail(self, html: str, url: str) -> ScrapeResult:
        soup = BeautifulSoup(html, "html.parser")
        title = soup.select_one("h1.notice-title")
        body = soup.select_one("div.notice-content")
        date = soup.select_one("time")
        return ScrapeResult(
            title=title.get_text(strip=True) if isinstance(title, Tag) else None,
            date_str=date.get_text(strip=True) if isinstance(date, Tag) else "",
            html_content=str(body) if isinstance(body, Tag) else None,
            images=[],
            attachments=[],
        )


_crawler = ExampleCollegeCrawler()
get_notice_links, scrape_detail = _crawler.legacy_exports()
CRAWLER_SPEC = _crawler.to_crawler_spec(
    get_links_name="get_notice_links",
    scrape_detail_name="scrape_detail",
)
```

## Notes

- Keep crawler modules focused on extraction only.
- Validation, de-duplication, and DB persistence are handled by crawl item pipelines.
- Use `request_meta={"retry_403": True}` only for hosts that need WAF-specific behavior.

