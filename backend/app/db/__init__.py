from pathlib import Path

import psycopg

INTERRUPTED = "서버가 다시 시작되어 작업이 끊겼습니다. 다시 분석해 주세요."


def init_db(database_url: str) -> None:
    """테이블이 없으면 만든다. 여러 번 실행해도 안전하다."""
    schema = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
    with psycopg.connect(database_url) as conn:
        conn.execute(schema)


def fail_interrupted_jobs(database_url: str) -> None:
    """작업은 서버 프로세스 안(BackgroundTasks)에서 돌므로, 서버가 새로 뜰 때 진행 중이던 작업은 모두 끊긴 것이다.
    실패로 바꿔 두어야 화면이 끝없이 기다리지 않고, 같은 영상을 다시 넣었을 때 새로 분석한다."""
    with psycopg.connect(database_url) as conn:
        conn.execute(
            "UPDATE analyses SET status = 'failed', progress = NULL, error = %s WHERE status IN ('pending', 'running')",
            (INTERRUPTED,),
        )
