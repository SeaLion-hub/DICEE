"""HTML 전처리(_clean_notice_html, slim_html) 품질·회귀 테스트."""

from app.services.ai_pipeline import _clean_notice_html

SHORT_NOTICE_HTML = """
<!DOCTYPE html>
<html>
<head><title>장학금 공지</title></head>
<body>
<nav>메뉴</nav>
<main>
  <h1>2026학년도 국가장학금 신청 안내</h1>
  <p>3학년 이상 재학생 중 성적 기준을 충족하는 분만 지원 가능합니다.</p>
  <ul>
    <li>서류 제출 마감: 2026년 3월 15일</li>
    <li>1차 면접: 3월 20일</li>
  </ul>
  <p>문의: 교무처 장학팀</p>
</main>
<footer>© 대학교</footer>
</body>
</html>
"""


LONG_NOTICE_HTML = """
<!DOCTYPE html>
<html>
<head><title>채용 공지</title></head>
<body>
<script>console.log('x');</script>
<nav>홈 공지 채용</nav>
<article>
  <h1>2026 상반기 인턴 채용</h1>
  <p>대상: 4학년 및 대학원생, 전공 무관.</p>
  <p>지원 자격: 학점 3.0 이상, 해당 학과 소속.</p>
  <table>
    <tr><th>일정</th><th>내용</th></tr>
    <tr><td>서류 마감</td><td>4월 10일</td></tr>
    <tr><td>면접</td><td>4월 20일</td></tr>
  </table>
  <img src="/poster.png" alt="채용 포스터: 지원 마감 4월 10일"/>
  <p>첨부: 포스터 참고. 자격 요건은 위와 같습니다.</p>
</article>
<footer>인사팀</footer>
</body>
</html>
"""


def test_clean_preserves_short_notice_key_phrases() -> None:
    """짧은 공지에서 핵심 일정·자격 문구가 유지된다."""
    cleaned = _clean_notice_html(SHORT_NOTICE_HTML)
    assert "3학년 이상" in cleaned
    assert "성적 기준" in cleaned or "지원 가능" in cleaned
    assert "서류 제출 마감" in cleaned or "3월 15일" in cleaned
    assert "1차 면접" in cleaned or "3월 20일" in cleaned
    assert "장학금" in cleaned or "국가장학금" in cleaned


def test_clean_preserves_long_notice_key_phrases() -> None:
    """긴 공지에서 일정·자격·첨부 안내 문구가 유지된다."""
    cleaned = _clean_notice_html(LONG_NOTICE_HTML)
    assert "4학년" in cleaned or "대학원생" in cleaned
    assert "학점 3.0" in cleaned or "지원 자격" in cleaned
    assert "서류 마감" in cleaned or "4월 10일" in cleaned
    assert "면접" in cleaned or "4월 20일" in cleaned
    assert "첨부" in cleaned or "포스터" in cleaned


def test_clean_includes_img_alt() -> None:
    """img alt 텍스트가 본문에 포함되고 img 태그는 제거된다."""
    cleaned = _clean_notice_html(LONG_NOTICE_HTML)
    assert "[이미지:" in cleaned and "채용 포스터" in cleaned
    assert "<img" not in cleaned.lower()


def test_clean_preserves_table_structure_in_slim_html() -> None:
    """slim_html은 표 구조(table/tr/th/td)를 유지한다."""
    cleaned = _clean_notice_html(LONG_NOTICE_HTML)
    assert "<table" in cleaned
    assert "<tr" in cleaned
    assert "<th" in cleaned
    assert "<td" in cleaned


def test_clean_strips_script_nav_footer() -> None:
    """script, nav, footer는 제거되어 본문만 남는다."""
    cleaned = _clean_notice_html(SHORT_NOTICE_HTML)
    assert "메뉴" not in cleaned
    cleaned_long = _clean_notice_html(LONG_NOTICE_HTML)
    assert "console.log" not in cleaned_long


def test_clean_length_cap() -> None:
    """전처리 결과는 12_000자 상한을 넘지 않는다."""
    long_html = "<p>" + "가나다 " * 5000 + "</p>"
    cleaned = _clean_notice_html(long_html)
    assert len(cleaned) <= 12_000


def test_clean_empty_input() -> None:
    """빈 입력은 빈 문자열을 반환한다."""
    assert _clean_notice_html("") == ""
    assert _clean_notice_html("   ") == ""


def test_clean_abbreviates_long_href() -> None:
    """긴 링크 URL은 프롬프트용으로 축약된다."""
    long_qs = "https://example.com/path?" + "x=1&" * 80 + "end=1"
    html = f'<p><a href="{long_qs}">신청</a></p>'
    cleaned = _clean_notice_html(html)
    assert long_qs not in cleaned
    assert "신청" in cleaned
    assert "[링크]" in cleaned or "example.com" in cleaned


def test_clean_drops_header_aside() -> None:
    html = """
    <html><body>
    <header>로고 공유</header>
    <aside>사이드 위젯</aside>
    <main><p>본문 핵심</p></main>
    </body></html>
    """
    cleaned = _clean_notice_html(html)
    assert "본문 핵심" in cleaned
    assert "로고 공유" not in cleaned
    assert "사이드 위젯" not in cleaned


def test_clean_smart_truncation_keeps_schedule_keyword() -> None:
    """긴 HTML에서 일정 키워드 구간이 단순 앞부분만 잘리는 것보다 우선 포함된다."""
    from unittest.mock import patch

    from app.core.config import settings

    filler = ("<p>잡음 문단입니다. " + "가나다 " * 400 + "</p>\n") * 8
    tail = "<p>서류 마감은 2026년 5월 1일이며 지원 자격은 재학생입니다.</p>"
    html = "<html><body>" + filler + tail + "</body></html>"
    with patch.object(settings, "ai_input_html_char_limit", 2500):
        cleaned = _clean_notice_html(html)
    assert len(cleaned) <= 2500
    assert "서류 마감" in cleaned or "지원 자격" in cleaned
