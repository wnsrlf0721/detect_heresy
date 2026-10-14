"""영상 하나를 실제로 추출해 단계별 시간과 결과를 출력한다. 판별(LLM)은 하지 않는다.

실행: uv run python -m scripts.try_extract https://youtu.be/...
"""

import sys
import time

from app.api.deps import get_pipeline


def main() -> None:
    started = time.time()
    result = get_pipeline().run(sys.argv[1], lambda stage: print(f"[{time.time() - started:5.1f}s] {stage}"))
    print(f"[{time.time() - started:5.1f}s] 완료: {result.title} ({result.duration}초)")
    for warning in result.warnings:
        print("경고:", warning)
    for source in ("caption", "stt", "ocr"):
        segments = [s for s in result.segments if s.source == source]
        print(f"\n--- {source} {len(segments)}구간")
        for segment in segments:
            print(segment.time, segment.text)


if __name__ == "__main__":
    main()
