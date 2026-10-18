"""판별 대상 구간에 앞뒤 구간을 문맥으로 붙인다.

음성 인식은 말을 몇 초 단위로 잘라서, 한 주장이 여러 구간에 나뉘어 담긴다
("약속하신 보혜사가 있죠." / "그분이 바로 우리 선생님입니다."). 구간 하나만 보면 뜻을 놓치므로
검색과 판별 모두 앞뒤 구간을 함께 본다.
"""

from dataclasses import dataclass

from app.schemas.analysis import Segment

CONTEXT_BEFORE = 2
CONTEXT_AFTER = 1


@dataclass(frozen=True)
class Target:
    index: int  # 입력 구간 목록에서의 번호. 1차 선별로 일부만 남아도 원래 구간을 가리킨다.
    segment: Segment
    before: list[str]
    after: list[str]

    @property
    def window_text(self) -> str:
        """검색에 쓰는 문맥 포함 텍스트."""
        return " ".join([*self.before, self.segment.text, *self.after])


def with_context(segments: list[Segment]) -> list[Target]:
    """구간마다 같은 출처의 앞뒤 구간을 붙인다. 입력은 출처별로 시간순이라는 전제다(추출 결과가 그렇다)."""
    order: dict[str, list[int]] = {}
    for index, segment in enumerate(segments):
        order.setdefault(segment.source, []).append(index)

    targets: list[Target] = []
    for index, segment in enumerate(segments):
        same_source = order[segment.source]
        position = same_source.index(index)
        before = same_source[max(0, position - CONTEXT_BEFORE) : position]
        after = same_source[position + 1 : position + 1 + CONTEXT_AFTER]
        targets.append(
            Target(
                index=index,
                segment=segment,
                before=[segments[i].text for i in before],
                after=[segments[i].text for i in after],
            )
        )
    return targets
