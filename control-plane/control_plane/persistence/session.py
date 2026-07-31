# 数据库会话:SQLite WAL,启用外键。数据目录在本地磁盘。
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..infrastructure.config import Settings
from .models import Base


def make_engine(db_path: str) -> Engine:
    # SQLite 连接串;check_same_thread=False 以允许 ASGI 线程访问
    url = f"sqlite:///{db_path}"
    engine = create_engine(url, connect_args={"check_same_thread": False}, future=True)

    @event.listens_for(engine, "connect")
    def _set_wal(dbapi_conn, _record):  # pragma: no cover - 简单设置
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")  # WAL 模式,支持读并发
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return engine


class Database:
    def __init__(self, settings: Settings) -> None:
        settings.ensure_data_dir()
        self.engine = make_engine(settings.db_path)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False, class_=Session)
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        s = self.SessionLocal()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()
