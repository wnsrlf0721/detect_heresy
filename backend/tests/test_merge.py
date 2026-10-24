from app.media.merge import merge_sources
from app.schemas.analysis import Segment
from app.schemas.transcript import TranscriptResult


def seg(time, text, source):
    return Segment(time=time, text=text, source=source)


def test_caption_is_used_for_speech_and_stt_is_dropped():
    segments = [
        seg("00:10", "예수님이 약속하신 보혜사는 오늘날 이 땅에 오셨습니다", "caption"),
        seg("00:11", "예수님이 약속하신 보혜사는 오늘날", "stt"),
    ]
    assert merge_sources(segments) == [segments[0]]


def test_stt_is_used_when_there_are_no_captions():
    segments = [seg("00:11", "음성으로 받아쓴 말", "stt"), seg("00:30", "요한복음 14장 26절", "ocr")]
    assert merge_sources(segments) == segments


def test_screen_text_repeating_nearby_speech_is_dropped():
    speech = seg("00:10", "보혜사는 오늘날 이 땅에 육체로 오신 약속의 목자입니다", "caption")
    burned_in = seg("00:12", "보혜사는 오늘날 이 땅에 육체로 오신", "ocr")
    # 같은 글자라도 시간이 멀면 말을 띄운 것이 아니라 따로 보여 준 글자다.
    far_away = seg("01:30", "보혜사는 오늘날 이 땅에 육체로 오신", "ocr")
    scripture = seg("00:14", "요한복음 14:26", "ocr")

    assert merge_sources([speech, burned_in, far_away, scripture]) == [speech, scripture, far_away]


def test_growing_slide_keeps_only_its_fullest_screen():
    steps = [
        seg("06:51", "썸의 정의: 1. 아침부터 저녁까지 연락이 계속된다", "ocr"),
        seg("06:57", "썸의 정의: 1. 아침부터 저녁까지 연락이 계속된다 2. 밥 먹으러 갈래? 대부분 OK", "ocr"),
        seg("07:03", "썸의 정의: 1. 아침부터 저녁까지 연락이 계속된다 2. 밥 먹으러 갈래? 대부분 OK 3. 자기 전까지 통화", "ocr"),
        # 한참 뒤에 같은 화면이 다시 나오면 따로 남긴다.
        seg("09:00", "썸의 정의: 1. 아침부터 저녁까지 연락이 계속된다", "ocr"),
    ]
    assert merge_sources(steps) == [steps[2], steps[3]]


def test_merged_lines_are_in_time_order_with_speech_first_on_ties():
    segments = [
        seg("00:05", "둘째 말", "caption"),
        seg("1:00:00", "한 시간 뒤", "caption"),
        seg("00:01", "화면 제목", "ocr"),
        seg("00:05", "같은 시각 화면 글자", "ocr"),
    ]
    assert [s.text for s in merge_sources(segments)] == ["화면 제목", "둘째 말", "같은 시각 화면 글자", "한 시간 뒤"]


def test_transcript_response_includes_merged_text():
    transcript = TranscriptResult(
        title="제목",
        duration=60,
        segments=[seg("00:01", "자막", "caption"), seg("00:02", "음성", "stt"), seg("00:03", "화면", "ocr")],
    )
    body = transcript.model_dump()
    assert [s["source"] for s in body["merged"]] == ["caption", "ocr"]
    # 응답으로 나간 값을 다시 읽어도(합친 텍스트는 계산한 값이라) 그대로 검증된다.
    assert TranscriptResult.model_validate(body) == transcript
