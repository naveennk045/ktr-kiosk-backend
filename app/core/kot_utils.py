from datetime import date
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.kot_counter import KotCounter


async def generate_kot(session: AsyncSession) -> tuple[date, int, str]:
    today = date.today()

    # Lock the row for today's date (or insert it)
    stmt = (
        select(KotCounter)
        .where(KotCounter.kot_date == today)
        .with_for_update()
    )
    result = await session.execute(stmt)
    counter = result.scalar_one_or_none()

    if counter is None:
        counter = KotCounter(kot_date=today, last_number=0)
        session.add(counter)
        await session.flush()

    counter.last_number += 1
    kot_number = counter.last_number
    kot_code = f"KTR-{kot_number}"

    # Commit happens in caller
    return today, kot_number, kot_code
