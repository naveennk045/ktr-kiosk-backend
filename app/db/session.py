from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from app.core.config import settings

class Base(DeclarativeBase):
    pass

from app.db.models.order import Order # noqa
from app.db.models.menu import Menu # noqa

from sqlalchemy.engine.url import make_url

def _get_db_config():
    url = settings.POSTGRES_DB_URL
    if not url:
        raise RuntimeError("POSTGRES_DB_URL is not set.")

    url_obj = make_url(url)

    # Ensure driver is asyncpg
    if url_obj.drivername.startswith("postgres"):
        url_obj = url_obj.set(drivername="postgresql+asyncpg")

    connect_args = {}

    # asyncpg does not support 'sslmode' in query params
    # We strip it and pass 'ssl' in connect_args
    query_params = dict(url_obj.query)
    if "sslmode" in query_params:
        ssl_mode = query_params.pop("sslmode")
        url_obj = url_obj.set(query=query_params)

        # Map sslmode to asyncpg ssl argument
        if ssl_mode == "require":
            connect_args["ssl"] = "require"
        elif ssl_mode == "disable":
            connect_args["ssl"] = False
        else:
             # For prefer, verify-ca, verify-full
            connect_args["ssl"] = ssl_mode

    return url_obj, connect_args

_db_url, _db_connect_args = _get_db_config()

engine = create_async_engine(
    _db_url,
    echo=settings.DEBUG_MODE,
    future=True,
    connect_args=_db_connect_args
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
