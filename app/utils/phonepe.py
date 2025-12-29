import json
import base64
import hashlib
from datetime import datetime, timedelta
from typing import Any, Dict
from app.core.config import settings

def make_base64(json_obj: Dict[str, Any]) -> str:
    json_str = json.dumps(json_obj, separators=(',', ':'))
    return base64.b64encode(json_str.encode("utf-8")).decode("utf-8")


def make_hash(input_str: str) -> str:
    return hashlib.sha256(input_str.encode("utf-8")).hexdigest()


def make_request_body(base64_payload: str) -> str:
    return json.dumps({"request": base64_payload})


def compute_x_verify_for_endpoint(base64_payload: str, endpoint_path: str, salt_key: str, salt_index: str) -> str:
    h = make_hash(base64_payload + endpoint_path + salt_key)
    return f"{h}###{salt_index}"


def compute_qr_expiry(now: datetime, expires_in_seconds: int) -> datetime:
    return now + timedelta(seconds=expires_in_seconds)


def verify_phonepe_callback_hash(base64_payload: str) -> str:
    """
    Computes the X-VERIFY hash for the S2S callback:
    SHA256(base64_payload + salt_key) + ### + salt_index
    """
    verification_str = base64_payload + settings.SALT_KEY
    hashed_str = make_hash(verification_str)  # Uses your existing make_hash
    return f"{hashed_str}###{settings.SALT_KEY_INDEX}"

