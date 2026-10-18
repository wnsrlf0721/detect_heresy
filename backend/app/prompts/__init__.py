"""프롬프트 로딩과 조립. 문구 자체는 이 폴더의 .md 파일에 둔다."""

import json
from pathlib import Path

from app.rag.context import Target
from app.schemas.analysis import Segment
from app.schemas.reference import Chunk

_DIR = Path(__file__).parent

def system_prompt() -> str:
    return (_DIR / "analyze_system.md").read_text(encoding="utf-8")


def ocr_system_prompt() -> str:
    return (_DIR / "ocr_system.md").read_text(encoding="utf-8")


def filter_system_prompt() -> str:
    return (_DIR / "filter_system.md").read_text(encoding="utf-8")


def _reference_block(chunk: Chunk) -> str:
    if chunk.kind == "orthodox":
        body = {"text": chunk.text, "scripture": chunk.metadata.get("scripture", [])}
    else:
        m = chunk.metadata
        body = {
            "group": m["group"],
            "claim": m["claim"],
            "keywords": m.get("keywords", []),
            "intent": m["intent"],
            "refutation": m["refutation"],
            "scripture": m.get("scripture", []),
        }
    return f'<reference id="{chunk.id}" kind="{chunk.kind}">\n{json.dumps(body, ensure_ascii=False, indent=2)}\n</reference>'


def _target_block(index: int, target: Target) -> str:
    parts = [f'<segment index="{index}" source="{target.segment.source}">']
    if target.before:
        parts.append(f"<before>{' '.join(target.before)}</before>")
    parts.append(f"<text>{target.segment.text}</text>")
    if target.after:
        parts.append(f"<after>{' '.join(target.after)}</after>")
    parts.append("</segment>")
    return "\n".join(parts)


def user_prompt(targets: list[tuple[int, Target]], references: list[Chunk]) -> str:
    reference_text = "\n".join(_reference_block(c) for c in references)
    segment_text = "\n".join(_target_block(index, target) for index, target in targets)
    return (
        f"<references>\n{reference_text}\n</references>\n\n"
        f"<segments>\n{segment_text}\n</segments>\n\n"
        "위 발언 구간을 참고 자료에 비추어 분석해 주십시오."
    )


def filter_user_prompt(segments: list[tuple[int, Segment]]) -> str:
    segment_text = "\n".join(
        f'<segment index="{index}" source="{segment.source}">{segment.text}</segment>' for index, segment in segments
    )
    return f"<segments>\n{segment_text}\n</segments>\n\n정밀 분석이 필요한 구간의 번호를 골라 주십시오."
