from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    pass


def _get_async_postgres_url() -> str:
    url = settings.POSTGRES_DB_URL
    if not url:
        raise RuntimeError(
            "POSTGRES_URL is not set. Provide an async URL like 'postgresql+asyncpg://user:pass@host:5432/db'.")
    if url.startswith("postgresql://") or url.startswith("postgres://"):
        # Force async driver
        url = url.replace("postgres://", "postgresql+asyncpg://").replace("postgresql://", "postgresql+asyncpg://", 1)
    if "+asyncpg://" not in url:
        raise RuntimeError("POSTGRES_URL must use an async driver, e.g., 'postgresql+asyncpg://...'")
    return url


engine = create_async_engine(_get_async_postgres_url(), echo=False, future=True)
SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
