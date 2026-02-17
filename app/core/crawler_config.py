"""
크롤러 설정 (사이트별 URL, 선택자, 규칙).
CAUTIONS: 코드를 수정하지 않고 config만 수정하여 대응 가능하도록 설계.
"""

from typing import Dict, Any

CRAWLER_CONFIG: Dict[str, Dict[str, Any]] = {
    "engineering": {
        "name": "공과대학",
        # 사용자님이 확인해주신 실제 리스트 페이지 주소
        "url": "https://engineering.yonsei.ac.kr/engineering/board/notice.do?mode=list&articleLimit=10",
        "type": "TYPE_A_LIST_NUM",
        "selectors": {
            "row": "tbody tr",
            "link": "a",
        },
    },
    # 나머지 단과대는 링크 및 구조 확인 전까지 보류합니다.
    # "freshman": {
    #     "name": "학부대학",
    #     "url": "...", 
    #     "type": "TYPE_B_URL_PARAM",
    #     "param_name": "articleNo",
    # },
}