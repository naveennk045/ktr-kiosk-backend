"""Kitchen Display System (KDS) — live orders, per-item status, Redis fan-out.

Import the router from ``app.kds.router`` (not from this package) to avoid import cycles
with ``app.core.dependencies`` and ``app.services.payment_service``.
"""

__all__: list[str] = []
