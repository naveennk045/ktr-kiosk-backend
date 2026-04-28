"""Pydantic models for Kitchen Display System APIs."""

from pydantic import BaseModel, Field

from app.db.models.order import OrderItemStatus


class KdsHealthResponse(BaseModel):
    service: str = Field(default="kds", description="Kitchen Display System")
    live_window_minutes: int = Field(description="Rolling window for Option B (see app.kds.constants)")
    note: str = Field(
        default="GET /kds/board for snapshot; WebSocket /kds/ws for live JSON; PATCH line order_status.",
    )


class KdsLineStatusPatch(BaseModel):
    status: OrderItemStatus = Field(
        description="Next line status: NOT_ACCEPTED → PREPARING → READY → COLLECTED",
    )
