from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from app.core.config import settings

class Base(DeclarativeBase):
    pass

def _get_async_postgres_url() -> str:
    url = settings.POSTGRES_DB_URL
    if not url:
        raise RuntimeError("POSTGRES_DB_URL is not set.")

    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    return url

engine = create_async_engine(
    _get_async_postgres_url(),
    echo=settings.DEBUG_MODE,
    future=True
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session