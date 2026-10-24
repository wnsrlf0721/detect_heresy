"""분석 전에 입력한 주소가 맞는 영상인지 확인하는 미리보기. 유튜브 oEmbed 로 제목과 썸네일을 가져온다."""

from typing import Protocol

import httpx

from app.errors import AnalysisError
from app.schemas.video import VideoPreview


class VideoNotFound(Exception):
    """영상이 없거나 비공개라 볼 수 없을 때."""


class PreviewSource(Protocol):
    def lookup(self, video_id: str) -> VideoPreview: ...


class OEmbedPreview:
    """유튜브 oEmbed API. API 키가 필요 없고, 영상이 없으면 404/400, 비공개면 403, 퍼가기 금지면 401 을 준다."""

    URL = "https://www.youtube.com/oembed"

    def __init__(self):
        self._client = httpx.Client(timeout=10)

    def lookup(self, video_id: str) -> VideoPreview:
        watch_url = f"https://www.youtube.com/watch?v={video_id}"
        try:
            response = self._client.get(self.URL, params={"url": watch_url, "format": "json"})
        except httpx.HTTPError as e:
            raise AnalysisError(f"영상 정보를 가져오지 못했습니다: {e}") from e
        if response.status_code == 401:
            # 영상은 있지만 퍼가기가 막혀 있어 제목을 주지 않는다. 썸네일은 영상 ID로 바로 볼 수 있다.
            return VideoPreview(video_id=video_id, thumbnail_url=_thumbnail(video_id), embeddable=False)
        if response.status_code in (400, 403, 404):
            raise VideoNotFound
        if response.status_code != 200:
            raise AnalysisError(f"영상 정보를 가져오지 못했습니다 ({response.status_code}).")
        body = response.json()
        return VideoPreview(
            video_id=video_id,
            title=body.get("title"),
            author=body.get("author_name"),
            thumbnail_url=body.get("thumbnail_url") or _thumbnail(video_id),
            embeddable=True,
        )


def _thumbnail(video_id: str) -> str:
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
