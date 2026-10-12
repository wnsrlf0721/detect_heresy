class AnalysisError(Exception):
    """판별을 끝내지 못했을 때. 메시지는 API 응답의 error 로 그대로 나간다."""
