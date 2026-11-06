"""Redis pub/sub + stream fan-out for KDS and TMS (multi-worker safe)."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

KDS_NOTIFY_CHANNEL = "kds:notify"
KDS_STREAM_KEY = "kds:stream"


def tms_snapshot_gen_key(store_id: int) -> str:
    """Counter bumped by every kitchen event for a store; versions the cached TMS snapshot."""
    return f"tms:snapshot:gen:{store_id}"


def tms_snapshot_key(store_id: int, gen: str) -> str:
    """Cached TMS snapshot JSON for one generation. A snapshot built while an event lands is
    written under the old generation, so it can never be served as current."""
    return f"tms:snapshot:{store_id}:{gen}"


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
    store_id = payload.get("store_id")
    try:
        # One round trip: invalidate the store's cached snapshot before subscribers refetch it.
        pipe = redis.pipeline(transaction=False)
        if store_id is not None:
            pipe.incr(tms_snapshot_gen_key(int(store_id)))
        pipe.publish(KDS_NOTIFY_CHANNEL, msg)
        pipe.xadd(
            KDS_STREAM_KEY,
            {"data": msg},
            maxlen=10_000,
            approximate=True,
        )
        await pipe.execute()
    except Exception as e:
        logger.warning("emit_kitchen_event failed: %s", e)
