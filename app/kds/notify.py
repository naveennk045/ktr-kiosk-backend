"""Redis pub/sub + stream fan-out for KDS and TMS (multi-worker safe)."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

KDS_NOTIFY_CHANNEL = "kds:notify"
KDS_STREAM_KEY = "kds:stream"


def line_ready_speech(kot_code: str, item_name: str) -> str:
    """Plain text for browser SpeechSynthesis (TMS); language handled client-side."""
    short = kot_code.removeprefix("KTR-") if kot_code.startswith("KTR-") else kot_code
    name = item_name or "Your order"
    return (
        f"Token number {short}. {name} is ready for pickup. "
        "Please collect from the counter."
    )


async def emit_kitchen_event(redis: Any | None, event_type: str, payload: dict[str, Any]) -> None:
    if redis is None:
        return
    msg = json.dumps({"type": event_type, "payload": payload})
    try:
        await redis.publish(KDS_NOTIFY_CHANNEL, msg)
        await redis.xadd(
            KDS_STREAM_KEY,
            {"data": msg},
            maxlen=10_000,
            approximate=True,
        )
    except Exception as e:
        logger.warning("emit_kitchen_event failed: %s", e)
