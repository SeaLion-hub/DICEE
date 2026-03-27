# gstack 스킬 사용 가이드

이 문서는 **Cursor(Composer·Chat)**에서 이 저장소에 포함된 **gstack 스킬**을 어디에 두었는지, 어떻게 불러 쓰면 되는지 정리한다. 워크플로의 최우선 안내는 루트 [`GSTACK.md`](../GSTACK.md)와 [`AGENTS.md`](../AGENTS.md)를 따른다.

---

## 1. 스킬이 있는 위치

| 구분 | 경로 |
|------|------|
| 커밋된 생성 스킬(권장 참조) | `.agents/skills/gstack/.agents/skills/` |
| 예: 리뷰 스킬 | `.agents/skills/gstack/.agents/skills/gstack-review/SKILL.md` |
| 로컬 전용 플랫 링크(선택) | `.agents/skills/gstack-*` (`setup` 후 생기며 **gitignore**) |

Cursor는 보통 위 경로의 `SKILL.md`를 **에이전트 스킬**로 인덱싱한다. 스킬이 안 보이면 창을 다시 로드하거나 아래 **초기 설정**을 한 번 실행한다.

---

## 2. Cursor에서 “어떻게” 쓰는가

gstack 스킬은 **별도 메뉴 버튼**이 아니라, 대화에서 **의도와 스킬 이름(또는 역할)**을 말하면 에이전트가 해당 스킬 설명을 따르도록 설계되어 있다.

### 2.1 Composer(Cmd+I) / Chat 공통

- **자연어로 단계를 말한다.** 예: “gstack으로 PR 랜딩 전 리뷰 해줘”, “배포 후 캐너리로 확인해줘”, “버그 원인 조사는 gstack-investigate 방식으로”.
- **스킬 이름을 그대로 적어도 된다.** Cursor가 스킬 목록에 올려 둔 이름과 맞추면 매칭이 잘 된다. 예: `gstack-review`, `gstack-ship`, `gstack-browse`.
- **파일 맥락이 필요하면 `@`로 붙인다.** 예: `@app/api/...` 변경분 리뷰, `@docs/...` 기준으로 문서 릴리스 정리. (스킬 자체를 `@`로 지정하는 UI는 환경마다 다를 수 있으므로, **요청 문장에 스킬명·목적을 명시**하는 방식이 가장 안정적이다.)

### 2.2 웹·QA·스크린샷이 필요할 때

- 프로젝트 정책상 **헤드리스 브라우저 QA**는 **gstack-browse**(또는 동일 계열)를 우선한다. `GSTACK.md`에 “임의 브라우저 MCP와 정책 충돌을 피하라”는 안내가 있다.
- 실제 크롬 창을 띄워 보고 싶다면 요청에 **gstack-connect-chrome**을 명시한다.

---

## 3. 스프린트 순서와 대응 스킬

`GSTACK.md`의 순서: **Think → Plan → Build → Review → Test → Ship → Reflect**

| 단계 | 할 일 예시 | 자주 쓰는 스킬 이름(요청에 포함) |
|------|------------|----------------------------------|
| Think | 아이디어·수요 정리 | `gstack-office-hours` |
| Plan | 전략·범위·설계 검토 | `gstack-plan-ceo-review`, `gstack-plan-eng-review`, `gstack-plan-design-review`, `gstack-design-consultation` |
| Build | 구현 (레포 규칙 준수) | (구현 자체는 `.cursor/rules/`; 필요 시 계획 스킬로 선행 검토) |
| Review | 머지 전 점검 | `gstack-review`, `gstack-autoplan`(자동 다각 리뷰 파이프라인) |
| Test | QA·버그 재현 | `gstack-qa`, `gstack-qa-only`(수정 없이 리포트만), `gstack-browse` |
| Ship | PR·배포 | `gstack-ship`, `gstack-land-and-deploy`, `gstack-canary`, `gstack-benchmark` |
| Reflect | 문서·회고·보안 점검 | `gstack-document-release`, `gstack-retro`, `gstack-cso` |

**디버깅·장애**는 단계와 무관하게 `gstack-investigate`를 요청하면 된다.

**안전·범위 제한**이 필요할 때:

- `gstack-careful` — 파괴적 명령 전 경고
- `gstack-freeze` — 특정 디렉터리만 편집 허용
- `gstack-guard` — careful + freeze 조합
- `gstack-unfreeze` — freeze 해제
- `gstack-upgrade` — gstack 업그레이드

**기타**: 배포 설정 정리 `gstack-setup-deploy`, 쿠키 가져오기 `gstack-setup-browser-cookies`, Codex CLI 연동 `gstack-codex`(해당 스킬이 활성화된 경우) 등.

---

## 4. 이 저장소와 충돌할 때 (반드시 읽기)

gstack 출력이 **레포 규칙**과 다르면 **항상 레포 규칙이 우선**이다 (`GSTACK.md` “Non-negotiables”).

- 아키텍처: 라우터 / 서비스 / 리포지토리 분리 — `.cursor/rules/architecture.mdc`
- 스택: SQLAlchemy 2.0 async, Pydantic v2 — `.cursor/rules/tech-stack.mdc`
- 코드 변경 후 **`pytest`** 실행
- 기능·버그픽스 완료 시 **`docs/WORK_LOG.md`** 한 줄
- 매뉴얼은 `docs/rules/`, Cursor 규칙은 `.cursor/rules/`만 (경로 혼용 금지)

---

## 5. 첫 클론·Windows에서 스킬이 안 잡힐 때

1. **Git Bash**에서 Bun·Node가 PATH에 오도록 한 뒤, 저장소 루트에서:

   ```bash
   export PATH="/c/Program Files/nodejs:/c/Users/$USER/.bun/bin:$PATH"
   cd .agents/skills/gstack && ./setup --host codex
   ```

2. Cursor **재시작 또는 창 다시 로드**.
3. 로컬 검증: `pytest tests/test_gstack_adoption.py -q` (CI와 동일 기대).

자세한 이유와 배경은 [`GSTACK.md`](../GSTACK.md) “First-time / new clone”, “Cursor verification”을 본다.

---

## 6. `todo.md`와의 관계

정책상 **`todo.md`는 선택**이며, 기준 흐름은 **gstack + `GSTACK.md`**다. `todo.md`를 쓰더라도 현재 스프린트 단계와 체크리스트를 맞추면 된다.

---

## 7. 요약 체크리스트

- [ ] 워크플로 질문은 먼저 **`GSTACK.md`**를 연다.
- [ ] Cursor에서는 **목적 + 스킬 이름**(예: `gstack-review`)을 문장에 넣는다.
- [ ] 코드/문서 맥락은 **`@파일`**로 붙인다.
- [ ] 스킬이 보이지 않으면 **`.agents/skills/gstack`에서 `./setup --host codex`** 후 Cursor 재로드.
- [ ] 스킬과 레포 규칙이 겹치면 **`.cursor/rules/`와 `pytest`가 우선**이다.
