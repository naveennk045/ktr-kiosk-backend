"""Pydantic models for Token Management System (TMS) APIs."""

from pydantic import BaseModel, Field


class TmsHealthResponse(BaseModel):
    service: str = Field(default="tms", description="Token Display System")
    live_window_minutes: int
    note: str = Field(
        default="SSR snapshot + SSE/WebSocket hydration will attach here; driven by same Option B window as KDS.",
    )
