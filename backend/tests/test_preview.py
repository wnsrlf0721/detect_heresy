"""영상 미리보기(GET /videos/preview)와 oEmbed 조회를 실제 호출 없이 검증한다."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_preview_source
from app.errors import AnalysisError
from app.main import app
from app.media.preview import OEmbedPreview, VideoNotFound
from app.schemas.video import VideoPreview


def make_oembed(response: httpx.Response):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return response

    preview = OEmbedPreview()
    preview._client = httpx.Client(transport=httpx.MockTransport(handler))
    return preview, requests


def test_oembed_returns_title_and_thumbnail():
    body = {"title": "보혜사 강의", "author_name": "어느 교회", "thumbnail_url": "https://i.ytimg.com/vi/AAAAAAAAAAA/hqdefault.jpg"}
    preview, requests = make_oembed(httpx.Response(200, json=body))

    result = preview.lookup("AAAAAAAAAAA")

    assert result == VideoPreview(
        video_id="AAAAAAAAAAA",
        title="보혜사 강의",
        author="어느 교회",
        thumbnail_url=body["thumbnail_url"],
        embeddable=True,
    )
    assert requests[0].url.params["url"] == "https://www.youtube.com/watch?v=AAAAAAAAAAA"


def test_oembed_unembeddable_video_still_exists():
    preview, _ = make_oembed(httpx.Response(401, text="Unauthorized"))

    result = preview.lookup("AAAAAAAAAAA")

    assert result.embeddable is False
    assert result.title is None
    assert result.thumbnail_url == "https://i.ytimg.com/vi/AAAAAAAAAAA/hqdefault.jpg"


@pytest.mark.parametrize("status", [400, 403, 404])
def test_oembed_missing_or_private_video(status):
    preview, _ = make_oembed(httpx.Response(status, text="Not Found"))

    with pytest.raises(VideoNotFound):
        preview.lookup("AAAAAAAAAAA")


def test_oembed_server_error_is_reported():
    preview, _ = make_oembed(httpx.Response(500, text="oops"))

    with pytest.raises(AnalysisError, match="500"):
        preview.lookup("AAAAAAAAAAA")


class FakePreviewSource:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.looked_up: list[str] = []

    def lookup(self, video_id):
        self.looked_up.append(video_id)
        if self.error:
            raise self.error
        return VideoPreview(video_id=video_id, title="제목", thumbnail_url="https://example.com/t.jpg", embeddable=True)


@pytest.fixture
def make_client():
    def _make(error=None):
        source = FakePreviewSource(error)
        app.dependency_overrides[get_preview_source] = lambda: source
        client = TestClient(app)
        client.source = source
        return client

    yield _make
    app.dependency_overrides.clear()


def test_preview_finds_video_from_any_url_form(make_client):
    client = make_client()

    response = client.get("/videos/preview", params={"url": "https://www.youtube.com/watch?v=AAAAAAAAAAA&t=30s"})

    assert response.status_code == 200
    assert response.json()["video_id"] == "AAAAAAAAAAA"
    assert client.source.looked_up == ["AAAAAAAAAAA"]


@pytest.mark.parametrize("url", ["https://example.com/watch?v=AAAAAAAAAAA", "https://www.youtube.com/@channel", "youtu.be"])
def test_preview_rejects_non_video_urls_without_lookup(make_client, url):
    client = make_client()

    response = client.get("/videos/preview", params={"url": url})

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)
    assert client.source.looked_up == []


def test_preview_reports_missing_video(make_client):
    client = make_client(VideoNotFound())

    response = client.get("/videos/preview", params={"url": "https://youtu.be/AAAAAAAAAAA"})

    assert response.status_code == 404
    assert "비공개" in response.json()["detail"]


def test_preview_reports_lookup_failure(make_client):
    client = make_client(AnalysisError("영상 정보를 가져오지 못했습니다 (500)."))

    response = client.get("/videos/preview", params={"url": "https://youtu.be/AAAAAAAAAAA"})

    assert response.status_code == 502
