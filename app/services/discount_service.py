import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from sqlalchemy import select, func, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.discount import Discount, DiscountUsage, DiscountApplicationType, DiscountType
from app.db.schemas.discount import DiscountCreate, DiscountUpdate

logger = logging.getLogger(__name__)

class DiscountService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_discount(self, discount_id: int) -> Optional[Discount]:
        stmt = select(Discount).where(Discount.id == discount_id, Discount.is_deleted.is_(False))
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_discount_by_code(self, code: str, store_id: Optional[int] = None) -> Optional[Discount]:
        stmt = select(Discount).where(
            func.upper(Discount.code) == code.strip().upper(),
            Discount.is_deleted.is_(False)
        )
        if store_id is not None:
            # Match either store-specific or global
            stmt = stmt.where(or_(Discount.store_id == store_id, Discount.store_id.is_(None)))
            # Prioritize store-specific (non-null store_id) over global (null store_id)
            stmt = stmt.order_by(Discount.store_id.desc())
        else:
            stmt = stmt.where(Discount.store_id.is_(None))

        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_usage_count(self, discount_id: int) -> int:
        stmt = select(func.count(DiscountUsage.id)).where(DiscountUsage.discount_id == discount_id)
        result = await self.db.execute(stmt)
        return result.scalar() or 0

    async def list_discounts(
        self,
        page: int = 1,
        limit: int = 20,
        store_id: Optional[int] = None,
        application_type: Optional[str] = None,
        is_active: Optional[bool] = None,
        search: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        offset = (page - 1) * limit
        stmt = select(Discount).where(Discount.is_deleted.is_(False))

        if store_id is not None:
            stmt = stmt.where(or_(Discount.store_id == store_id, Discount.store_id.is_(None)))
        if application_type:
            stmt = stmt.where(Discount.application_type == application_type.upper())
        if is_active is not None:
            stmt = stmt.where(Discount.is_active == is_active)
        if search:
            search_pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    Discount.name.ilike(search_pattern),
                    Discount.code.ilike(search_pattern)
                )
            )

        stmt = stmt.order_by(Discount.id.desc()).offset(offset).limit(limit)
        result = await self.db.execute(stmt)
        discounts = result.scalars().all()

        # Format and append usage counts
        formatted_discounts = []
        for d in discounts:
            usage_count = await self.get_usage_count(d.id)
            formatted_discounts.append({
                "id": d.id,
                "store_id": d.store_id,
                "name": d.name,
                "application_type": d.application_type,
                "code": d.code,
                "discount_type": d.discount_type,
                "value": float(d.value) if d.value is not None else None,
                "max_discount_amount": float(d.max_discount_amount) if d.max_discount_amount is not None else None,
                "min_order_amount": float(d.min_order_amount) if d.min_order_amount is not None else None,
                "usage_limit": d.usage_limit,
                "start_date": d.start_date,
                "end_date": d.end_date,
                "is_active": d.is_active,
                "is_deleted": d.is_deleted,
                "created_at": d.created_at,
                "updated_at": d.updated_at,
                "usage_count": usage_count
            })

        return formatted_discounts

    async def create_discount(self, obj_in: DiscountCreate, created_by: Optional[int] = None) -> Discount:
        db_obj = Discount(
            store_id=obj_in.store_id,
            name=obj_in.name,
            application_type=obj_in.application_type.upper(),
            code=obj_in.code.strip().upper() if obj_in.code else None,
            discount_type=obj_in.discount_type.upper(),
            value=obj_in.value,
            max_discount_amount=obj_in.max_discount_amount,
            min_order_amount=obj_in.min_order_amount,
            usage_limit=obj_in.usage_limit,
            start_date=obj_in.start_date,
            end_date=obj_in.end_date,
            is_active=obj_in.is_active if obj_in.is_active is not None else True,
            created_by=created_by
        )
        self.db.add(db_obj)
        await self.db.commit()
        await self.db.refresh(db_obj)
        return db_obj

    async def update_discount(self, discount_id: int, obj_in: DiscountUpdate) -> Optional[Discount]:
        db_obj = await self.get_discount(discount_id)
        if not db_obj:
            return None

        update_data = obj_in.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if field == "application_type" and value:
                value = value.upper()
            elif field == "code" and value:
                value = value.strip().upper()
            elif field == "discount_type" and value:
                value = value.upper()
            setattr(db_obj, field, value)

        await self.db.commit()
        await self.db.refresh(db_obj)
        return db_obj

    async def update_discount_status(self, discount_id: int, is_active: bool) -> Optional[Discount]:
        db_obj = await self.get_discount(discount_id)
        if not db_obj:
            return None
        db_obj.is_active = is_active
        await self.db.commit()
        await self.db.refresh(db_obj)
        return db_obj

    async def delete_discount(self, discount_id: int) -> bool:
        db_obj = await self.get_discount(discount_id)
        if not db_obj:
            return False
        db_obj.is_deleted = True
        await self.db.commit()
        return True

    async def validate_discount(
        self,
        application_type: str,
        code: Optional[str] = None,
        store_id: Optional[int] = None,
        cart_amount: float = 0.0
    ) -> Dict[str, Any]:
        """
        Validates the discount rules and calculates the discount amount.
        """
        app_type = application_type.upper()
        discount = None

        if app_type == DiscountApplicationType.COUPON.value:
            if not code:
                return {
                    "valid": False,
                    "message": "Coupon code is required for COUPON application type."
                }
            discount = await self.get_discount_by_code(code, store_id)
            if not discount:
                return {
                    "valid": False,
                    "message": f"Coupon code '{code}' not found or is not valid for this store."
                }
        else:
            # For AUTOMATIC, LOYALTY, or REFERRAL, resolve active discounts of that type
            stmt = select(Discount).where(
                Discount.application_type == app_type,
                Discount.is_active.is_(True),
                Discount.is_deleted.is_(False)
            )
            if store_id is not None:
                stmt = stmt.where(or_(Discount.store_id == store_id, Discount.store_id.is_(None)))
                stmt = stmt.order_by(Discount.store_id.desc(), Discount.id.desc())
            else:
                stmt = stmt.where(Discount.store_id.is_(None))
                stmt = stmt.order_by(Discount.id.desc())

            result = await self.db.execute(stmt)
            discounts = result.scalars().all()
            
            # Find the best one matching the criteria
            for d in discounts:
                # Check min order amount
                min_amt = float(d.min_order_amount) if d.min_order_amount is not None else 0.0
                if cart_amount >= min_amt:
                    discount = d
                    break
            
            if not discount:
                return {
                    "valid": False,
                    "message": f"No active {app_type} discount available for cart amount {cart_amount}."
                }

        # 1. Active / Deleted Check
        if not discount.is_active or discount.is_deleted:
            return {
                "valid": False,
                "message": f"Discount is inactive or has been deleted."
            }

        # 2. Date Validity Check
        now = datetime.now(timezone.utc)
        if discount.start_date:
            start_date_utc = discount.start_date.astimezone(timezone.utc) if discount.start_date.tzinfo else discount.start_date.replace(tzinfo=timezone.utc)
            if now < start_date_utc:
                return {
                    "valid": False,
                    "message": f"Discount has not started yet."
                }
        if discount.end_date:
            end_date_utc = discount.end_date.astimezone(timezone.utc) if discount.end_date.tzinfo else discount.end_date.replace(tzinfo=timezone.utc)
            if now > end_date_utc:
                return {
                    "valid": False,
                    "message": f"Discount has expired."
                }

        # 3. Usage Limit Check
        if discount.usage_limit is not None:
            usage_count = await self.get_usage_count(discount.id)
            if usage_count >= discount.usage_limit:
                return {
                    "valid": False,
                    "message": f"Discount usage limit has been reached."
                }

        # 4. Minimum Order Amount Check
        min_order = float(discount.min_order_amount) if discount.min_order_amount is not None else 0.0
        if cart_amount < min_order:
            return {
                "valid": False,
                "message": f"Minimum order amount of {min_order} required. Cart value is {cart_amount}."
            }

        # 5. Calculation
        discount_value = float(discount.value) if discount.value is not None else 0.0
        calculated_amount = 0.0

        if discount.discount_type == DiscountType.PERCENTAGE.value:
            calculated_amount = cart_amount * (discount_value / 100.0)
            if discount.max_discount_amount is not None:
                max_amt = float(discount.max_discount_amount)
                calculated_amount = min(calculated_amount, max_amt)
        elif discount.discount_type == DiscountType.FIXED_AMOUNT.value:
            calculated_amount = discount_value
        elif discount.discount_type == DiscountType.FREE_SHIPPING.value:
            calculated_amount = discount_value

        # Cap the discount amount at the actual cart amount
        calculated_amount = min(calculated_amount, cart_amount)
        calculated_amount = max(calculated_amount, 0.0)

        return {
            "valid": True,
            "discount_id": discount.id,
            "discount_type": discount.discount_type,
            "discount_value": discount_value,
            "discount_amount": calculated_amount,
            "message": "Discount applied successfully"
        }

    async def get_eligible_discounts(
        self,
        application_type: Optional[str] = None,
        store_id: Optional[int] = None,
        cart_amount: float = 0.0
    ) -> List[Dict[str, Any]]:
        """
        Retrieves active discounts that are valid for the given cart amount and store.
        """
        stmt = select(Discount).where(
            Discount.is_active.is_(True),
            Discount.is_deleted.is_(False)
        )
        if store_id is not None:
            stmt = stmt.where(or_(Discount.store_id == store_id, Discount.store_id.is_(None)))
        else:
            stmt = stmt.where(Discount.store_id.is_(None))

        if application_type:
            stmt = stmt.where(Discount.application_type == application_type.upper())

        result = await self.db.execute(stmt)
        discounts = result.scalars().all()

        eligible = []
        for d in discounts:
            # Quick checks
            now = datetime.now(timezone.utc)
            if d.start_date:
                start_date_utc = d.start_date.astimezone(timezone.utc) if d.start_date.tzinfo else d.start_date.replace(tzinfo=timezone.utc)
                if now < start_date_utc:
                    continue
            if d.end_date:
                end_date_utc = d.end_date.astimezone(timezone.utc) if d.end_date.tzinfo else d.end_date.replace(tzinfo=timezone.utc)
                if now > end_date_utc:
                    continue

            if d.usage_limit is not None:
                usage_count = await self.get_usage_count(d.id)
                if usage_count >= d.usage_limit:
                    continue

            min_amt = float(d.min_order_amount) if d.min_order_amount is not None else 0.0
            if cart_amount < min_amt:
                continue

            usage_count = await self.get_usage_count(d.id)
            eligible.append({
                "id": d.id,
                "store_id": d.store_id,
                "name": d.name,
                "application_type": d.application_type,
                "code": None,
                "discount_type": d.discount_type,
                "value": float(d.value) if d.value is not None else None,
                "max_discount_amount": float(d.max_discount_amount) if d.max_discount_amount is not None else None,
                "min_order_amount": min_amt,
                "usage_limit": d.usage_limit,
                "start_date": d.start_date,
                "end_date": d.end_date,
                "is_active": d.is_active,
                "is_deleted": d.is_deleted,
                "created_at": d.created_at,
                "updated_at": d.updated_at,
                "usage_count": usage_count
            })

        return eligible

    async def record_discount_usage(
        self,
        discount_id: int,
        order_id: int,
        discount_amount: float
    ) -> DiscountUsage:
        usage = DiscountUsage(
            discount_id=discount_id,
            order_id=order_id,
            discount_amount=discount_amount
        )
        self.db.add(usage)
        await self.db.commit()
        await self.db.refresh(usage)
        logger.info(f"Recorded discount usage: discount_id={discount_id}, order_id={order_id}, amount={discount_amount}")
        return usage
