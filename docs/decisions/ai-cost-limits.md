# AI 추출 비용·입력 한도 정책

**관련**: [ai-extraction-schema.md](ai-extraction-schema.md), `app/core/config/base.py`, `app/services/ai/extractor.py`.

## 요약

- **HTML**: `ai_input_html_char_limit`(기본 12_000)로 slim HTML 길이 상한. `app/services/ai_pipeline._clean_notice_html`에서 적용.
- **Vision 게이트**: `ai_vision_gate_enabled`가 True이면 긴 텍스트 공지에서 이미지 URL을 모델에 넣지 않거나(`ai_vision_max_images_passive`) 적게 넣어 Vision 토큰을 줄인다. 본문 없음·짧은 본문·제목 키워드 매칭 시 `ai_vision_max_images_active`까지 허용.
- **단일 패스**: 대분류+전체 스키마를 한 번의 구조화 호출로 추출한다.
- **Instructor 재시도**: `ai_extraction_max_retries`(기본 3). 프로바이더가 인자를 지원하지 않으면 TypeError 시 재시도 없이 호출한다.
- **모델 라우팅**: `ai_extraction_model_routing_enabled`(기본 False). True일 때 짧은 본문·비중요 제목은 `gemini_model_light`, taxonomy 검증 실패 시 한 번 `gemini_model`로 에스컬레이션.

## Quality gates

- `pytest` 전체 통과.
- 운영 전: 샘플 공지로 토큰·fallback 비율·taxonomy 실패율을 변경 전후 비교.
