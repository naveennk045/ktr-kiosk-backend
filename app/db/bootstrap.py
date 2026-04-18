"""
Startup hook: warn if no stores exist. Store rows and all credentials must be inserted
via SQL (e.g. scripts/sample_data_ktr_bandra_versova.sql) or your own migration.
"""
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.store import Store

logger = logging.getLogger(__name__)


async def ensure_default_store(session: AsyncSession) -> None:
    count = (
        await session.execute(select(func.count()).select_from(Store.__table__))
    ).scalar_one()
    if count and int(count) > 0:
        return

    logger.warning(
        "No rows in `stores`. Load outlets and credentials via SQL "
        "(see scripts/sample_data_ktr_bandra_versova.sql) or insert into "
        "stores / store_petpooja_credentials / store_phonepe_credentials / "
        "store_pinelabs_credentials / kiosk_terminals."
    )
