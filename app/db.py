"""Neon 연결 (커넥션 풀)."""
import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app import config

pool = None


def open_pool():
    global pool
    pool = ConnectionPool(
        config.DATABASE_URL,
        min_size=1,
        max_size=4,
        kwargs={"row_factory": dict_row},
        configure=register_vector,
        # Neon 무료 요금제는 쉬는 동안 연결을 끊는다. 꺼낼 때 살아 있는지 검사한다.
        check=ConnectionPool.check_connection,
        open=True,
    )


def close_pool():
    if pool is not None:
        pool.close()


def query(sql, params=None):
    """SELECT 실행 후 행 목록(dict)을 돌려준다. 연결이 끊겼으면 1번 다시 시도한다."""
    for attempt in (1, 2):
        try:
            with pool.connection() as conn:
                return conn.execute(sql, params).fetchall()
        except psycopg.OperationalError:
            if attempt == 2:
                raise
