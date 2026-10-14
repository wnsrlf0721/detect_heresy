"""영상 → 텍스트 추출. 자막(caption), 음성(stt), 화면 글자(ocr) 세 출처를 구간으로 만든다."""


def format_time(seconds: float) -> str:
    """초를 구간의 time 형식("02:15", 한 시간이 넘으면 "1:02:15")으로 바꾼다."""
    total = int(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"
