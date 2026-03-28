from __future__ import annotations

from unittest.mock import patch

from app.domain.contracts.ai_extraction import NoticeAIExtraction, NoticeCategory
from app.services.ai.streaming import NoticeExtractionDraft, stream_notice_extraction


def test_notice_extraction_draft_is_pydantic_model() -> None:
    """Streaming Draft 모델은 Pydantic BaseModel이어야 한다."""
    draft = NoticeExtractionDraft(category="scholarship", sub_category="장학", summary="요약")
    assert isinstance(draft, NoticeExtractionDraft)
    assert draft.category == "scholarship"
    assert draft.sub_category == "장학"
    assert draft.summary == "요약"


def test_stream_notice_extraction_returns_strict_model_on_completion() -> None:
    """Streaming 제너레이터는 최종적으로 NoticeAIExtraction strict 모델을 반환한다."""

    class DummyPartial:
        def __init__(self, model: NoticeExtractionDraft) -> None:
            self._model = model

        def to_model(self) -> NoticeExtractionDraft:
            return self._model

    def _fake_create(**kwargs):
        draft = NoticeExtractionDraft(
            category=NoticeCategory.SCHOLARSHIP.value,
            sub_category="국가장학금",
            summary="장학금 요약",
        )
        yield DummyPartial(draft)

    with patch("app.services.ai.streaming._get_instructor_client") as mock_client_factory:
        client = mock_client_factory.return_value
        client.create.side_effect = _fake_create

        gen = stream_notice_extraction("<p>html</p>", image_urls=None)
        strict_result = None
        try:
            while True:
                partial = next(gen)
                assert isinstance(partial.to_model(), NoticeExtractionDraft)
        except StopIteration as e:
            strict_result = e.value

    assert strict_result is not None
    assert isinstance(strict_result, NoticeAIExtraction)
    assert strict_result.category == NoticeCategory.SCHOLARSHIP
    assert strict_result.sub_category == "국가장학금"
    assert strict_result.summary == "장학금 요약"
    assert strict_result.target_departments == []
    restored = NoticeAIExtraction.model_validate(strict_result.model_dump(mode="json"))
    assert restored.category == strict_result.category
    assert restored.sub_category == strict_result.sub_category


def test_streaming_final_result_round_trips_like_non_streaming() -> None:
    """스트리밍 최종 결과는 NoticeAIExtraction strict 기준으로 round-trip 가능해야 한다.

    (non-streaming과 동등한 품질).
    """

    class DummyPartial:
        def __init__(self, model: NoticeExtractionDraft) -> None:
            self._model = model

        def to_model(self) -> NoticeExtractionDraft:
            return self._model

    def _fake_create(**kwargs):
        yield DummyPartial(
            NoticeExtractionDraft(
                category=NoticeCategory.EMPLOYMENT.value,
                sub_category="인턴",
                summary="인턴 채용 요약",
            )
        )

    with patch("app.services.ai.streaming._get_instructor_client") as m:
        m.return_value.create.side_effect = _fake_create
        gen = stream_notice_extraction("<p>채용 공지</p>", image_urls=None)
        try:
            while True:
                next(gen)
        except StopIteration as e:
            strict_result = e.value

    assert isinstance(strict_result, NoticeAIExtraction)
    dumped = strict_result.model_dump(mode="json")
    NoticeAIExtraction.model_validate(dumped)
    assert strict_result.category == NoticeCategory.EMPLOYMENT
    assert strict_result.sub_category == "인턴"
