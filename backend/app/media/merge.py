"""자막·음성·화면 글자 세 출처를 영상 하나의 텍스트로 합친다.

자막과 음성 인식은 같은 말을 담고 있고, 화면 글자도 말을 그대로 띄운 자막인 경우가 많다. 세 출처를 나란히
보여 주면 같은 내용을 세 번 읽게 되므로, 화면에는 합친 텍스트를 보여 준다. 판별 입력은 바꾸지 않는다.
"""

from app.media import bigrams, parse_time
from app.schemas.analysis import Segment

# 말은 한 출처만 쓴다. 사람이 올리거나 유튜브가 만든 자막이 음성 인식보다 대체로 정확하다.
SPEECH_PRIORITY = ("caption", "stt")
# 화면 글자가 이 시간 안의 말과 이만큼 겹치면, 말을 화면에 띄운 것으로 보고 뺀다.
SCREEN_REPEAT_SECONDS = 20
SCREEN_REPEAT_OVERLAP = 0.6
# 항목이 하나씩 늘어나는 발표 화면은 앞 장면이 다음 장면에 거의 다 들어 있다. 이 시간 안에 이만큼 들어 있으면
# 가장 완성된 마지막 장면만 남긴다.
SCREEN_GROWS_SECONDS = 30
SCREEN_GROWS_OVERLAP = 0.8


def _contained(inner: Segment, outer: Segment, seconds: int, overlap: float) -> bool:
    words = bigrams(inner.text)
    if not words or inner.time is None or outer.time is None:
        return False
    if abs(parse_time(outer.time) - parse_time(inner.time)) > seconds:
        return False
    return len(words & bigrams(outer.text)) / len(words) >= overlap


def _repeats_speech(screen: Segment, speech: list[Segment]) -> bool:
    words = bigrams(screen.text)
    if not words or screen.time is None:
        return False
    at = parse_time(screen.time)
    nearby: set[str] = set()
    for segment in speech:
        if segment.time is not None and abs(parse_time(segment.time) - at) <= SCREEN_REPEAT_SECONDS:
            nearby |= bigrams(segment.text)
    return len(words & nearby) / len(words) >= SCREEN_REPEAT_OVERLAP


def merge_sources(segments: list[Segment]) -> list[Segment]:
    """말 한 출처와, 말과 겹치지 않는 화면 글자를 시간순으로 합친다. 같은 시각이면 말이 먼저다."""
    speech: list[Segment] = []
    for source in SPEECH_PRIORITY:
        speech = [s for s in segments if s.source == source]
        if speech:
            break
    screen = [s for s in segments if s.source == "ocr" and not _repeats_speech(s, speech)]
    screen = [
        s
        for s, after in zip(screen, [*screen[1:], None])
        if after is None or not _contained(s, after, SCREEN_GROWS_SECONDS, SCREEN_GROWS_OVERLAP)
    ]
    others = [s for s in segments if s.source not in (*SPEECH_PRIORITY, "ocr")]
    # sorted 는 안정 정렬이라, 시각이 같으면 넣은 순서(말 → 화면 글자)를 지킨다.
    return sorted(
        speech + screen + others, key=lambda s: (s.time is None, parse_time(s.time) if s.time else 0)
    )
