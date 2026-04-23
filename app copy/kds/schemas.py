"""Pydantic models for Kitchen Display System APIs."""

from pydantic import BaseModel, Field

from app.db.models.order import KitchenLineStatus


class KdsHealthResponse(BaseModel):
    service: str = Field(default="kds", description="Kitchen Display System")
    live_window_minutes: int = Field(description="Rolling window for Option B (see app.kds.constants)")
    note: str = Field(
        default="GET /kds/board for snapshot; WebSocket /kds/ws for live JSON; PATCH line status to advance items.",
    )


class KdsLineStatusPatch(BaseModel):
    status: KitchenLineStatus = Field(description="Next kitchen status for this line")
