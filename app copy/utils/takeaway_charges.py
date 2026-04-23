"""
Takeaway packing charge rules (server is source of truth).

- ₹10 per ordered unit (sum of line quantities), before tax
- 5% tax on that amount
- Pre-tax cap: ₹100; tax-inclusive cap: ₹105
"""
from app.utils.tax_utils import money

TAKEAWAY_PER_UNIT_EXCLUDE_TAX = 10.0
TAKEAWAY_TAX_RATE = 0.05  # 5%
TAKEAWAY_CAP_EXCLUDE_TAX = 100.0
TAKEAWAY_CAP_INCLUDE_TAX = 105.0


def compute_takeaway_charges(total_item_quantity: int) -> tuple[float, float]:
    """
    Returns (exclude_tax, include_tax). For dine-in use quantity 0 or skip caller.
    """
    if total_item_quantity < 1:
        return 0.0, 0.0
    exclude = min(
        float(total_item_quantity) * TAKEAWAY_PER_UNIT_EXCLUDE_TAX,
        TAKEAWAY_CAP_EXCLUDE_TAX,
    )
    include = min(
        money(exclude * (1.0 + TAKEAWAY_TAX_RATE)),
        TAKEAWAY_CAP_INCLUDE_TAX,
    )
    return exclude, include
