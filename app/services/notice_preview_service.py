"""공지 임시 검수 페이지용 서비스."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.notice_repository import list_recent_notices_for_college_preview


@dataclass(frozen=True)
class NoticePreviewRow:
    title: str
    published_at: str
    url: str
    content_url: str
    image_urls: list[str]
    attachment_names: list[str]
    eligibility: list[str]
    dates: list[str]
    main_categories: list[str]
    sub_categories: list[str]


class NoticePreviewService:
    """임시 검수 화면에 필요한 필드를 평탄화해서 반환한다."""

    async def get_engineering_preview(
        self,
        session: AsyncSession,
        *,
        limit: int = 30,
    ) -> list[NoticePreviewRow]:
        notices = await list_recent_notices_for_college_preview(
            session,
            college_external_id="engineering",
            limit=limit,
        )
        rows: list[NoticePreviewRow] = []
        for notice in notices:
            published_at = ""
            if notice.published_at is not None:
                published_at = (
                    notice.published_at.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
                )

            content_url = ""
            if notice.notice_content is not None:
                content_url = str(notice.notice_content.content_url or "").strip()

            image_urls = self._extract_image_urls(notice.images)
            attachment_names = self._extract_attachment_names(notice.attachments)
            eligibility = [str(x).strip() for x in (notice.eligibility or []) if str(x).strip()]
            dates = self._extract_dates(notice.dates)
            main_categories, sub_categories = self._extract_taxonomy(
                taxonomy_mappings=None,
                ai_extracted_json=notice.ai_extracted_json,
            )

            rows.append(
                NoticePreviewRow(
                    title=notice.title or "",
                    published_at=published_at,
                    url=notice.url or "",
                    content_url=content_url,
                    image_urls=image_urls,
                    attachment_names=attachment_names,
                    eligibility=eligibility,
                    dates=dates,
                    main_categories=main_categories,
                    sub_categories=sub_categories,
                )
            )
        return rows

    @staticmethod
    def _extract_image_urls(images: list[dict] | None) -> list[str]:
        urls: list[str] = []
        for img in images or []:
            if not isinstance(img, dict):
                continue
            raw = str(img.get("url") or img.get("src") or "").strip()
            if raw:
                urls.append(raw)
        return urls

    @staticmethod
    def _extract_attachment_names(attachments: list[dict] | None) -> list[str]:
        names: list[str] = []
        for item in attachments or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("filename") or item.get("url") or "").strip()
            if name:
                names.append(name)
        return names

    @staticmethod
    def _extract_dates(dates: list[dict] | None) -> list[str]:
        out: list[str] = []
        for item in dates or []:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or item.get("kind") or "date").strip()
            starts_at = str(item.get("starts_at") or item.get("start_date_raw") or "").strip()
            ends_at = str(item.get("ends_at") or item.get("end_date_raw") or "").strip()
            if starts_at and ends_at:
                out.append(f"{label}: {starts_at} ~ {ends_at}")
            elif starts_at:
                out.append(f"{label}: {starts_at}")
            elif ends_at:
                out.append(f"{label}: {ends_at}")
            else:
                date_raw = str(item.get("date_raw") or "").strip()
                if date_raw:
                    out.append(f"{label}: {date_raw}")
        return out

    @staticmethod
    def _extract_taxonomy(
        *,
        taxonomy_mappings: list | None,
        ai_extracted_json: dict | None,
    ) -> tuple[list[str], list[str]]:
        main: list[str] = []
        sub: list[str] = []
        for row in taxonomy_mappings or []:
            m = str(getattr(row, "main_category", "")).strip()
            s = str(getattr(row, "sub_category", "")).strip()
            if m and m not in main:
                main.append(m)
            if s and s not in sub:
                sub.append(s)

        # taxonomy 정규화 테이블이 없는 환경(마이그레이션 전)에서는 ai_extracted_json을 fallback으로 사용.
        payload = ai_extracted_json or {}
        for m in payload.get("main_categories", []) or []:
            main_text = str(m).strip()
            if main_text and main_text not in main:
                main.append(main_text)
        for mapping in payload.get("taxonomy_mappings", []) or []:
            if not isinstance(mapping, dict):
                continue
            main_text = str(mapping.get("main_category") or "").strip()
            if main_text and main_text not in main:
                main.append(main_text)
            for s in mapping.get("sub_categories", []) or []:
                sub_text = str(s).strip()
                if sub_text and sub_text not in sub:
                    sub.append(sub_text)
        return main, sub
