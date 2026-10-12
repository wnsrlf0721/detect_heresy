from pathlib import Path

import psycopg


def init_db(database_url: str) -> None:
    """테이블이 없으면 만든다. 여러 번 실행해도 안전하다."""
    schema = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
    with psycopg.connect(database_url) as conn:
        conn.execute(schema)
