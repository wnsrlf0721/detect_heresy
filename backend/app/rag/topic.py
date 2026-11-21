"""영상 대주제 정리. 주제 임베딩으로 비슷한 주제의 이전 분석을 찾는다."""

from app import prompts
from app.rag.embedder import Embedder
from app.rag.llm import TopicWriter
from app.schemas.transcript import TranscriptResult
from app.schemas.video import VideoTopic
from app.timing import measure


def topic_text(topic: VideoTopic) -> str:
    """임베딩에 쓰는 텍스트. 영상끼리 비교하므로 저장할 때와 찾을 때 같은 형태를 쓴다."""
    return f"{topic.title}\n{topic.summary}\n{', '.join(topic.keywords)}"


class TopicService:
    def __init__(self, writer: TopicWriter, embedder: Embedder):
        self._writer = writer
        self._embedder = embedder

    def summarize(self, transcript: TranscriptResult) -> tuple[VideoTopic, list[float]]:
        with measure("topic_llm"):
            raw = self._writer.write(prompts.topic_system_prompt(), prompts.topic_user_prompt(transcript))
        topic = VideoTopic(title=raw.title, summary=raw.summary, keywords=raw.keywords)
        # 저장된 주제끼리 비교하므로 양쪽 모두 document 로 임베딩한다.
        with measure("topic_embedding"):
            embedding = self._embedder.embed([topic_text(topic)], "document")[0]
        return topic, embedding
