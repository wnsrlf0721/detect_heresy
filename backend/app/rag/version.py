"""판별 버전. 같은 영상이라도 이 값이 다르면 저장된 분석을 돌려주지 않고 다시 판별한다.

기준 데이터(data/orthodox, data/heresy), 판별에 쓰는 프롬프트, 모델 설정, 엔진 코드 버전(ENGINE_REVISION)이
하나라도 바뀌면 값이 바뀐다.
"""

import hashlib

from app.config import Settings
from app.prompts import ANALYSIS_PROMPT_FILES
from app.rag.corpus import DATA_DIR
from app.rag.engine import ENGINE_REVISION


def analysis_version(settings: Settings) -> str:
    digest = hashlib.sha256()
    files = sorted((DATA_DIR / "orthodox").glob("*.yaml")) + sorted((DATA_DIR / "heresy").glob("*.yaml"))
    for path in [*files, *ANALYSIS_PROMPT_FILES]:
        digest.update(path.name.encode())
        # git 이 Windows 에서 줄바꿈을 바꿔도 같은 내용으로 보도록 맞춘다.
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    for part in (settings.llm_model, settings.llm_effort, settings.filter_model, str(ENGINE_REVISION)):
        digest.update(part.encode())
    return digest.hexdigest()[:16]
