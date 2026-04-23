"""Kitchen Display System (KDS) — live orders, per-item status, Redis Stream (planned)."""

from app.kds.router import router

__all__ = ["router"]
