import base64
import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Dict


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


def verify_phonepe_callback_hash(
    base64_payload: str,
    salt_key: str | None = None,
    salt_key_index: str | None = None,
) -> str:
    """
    Computes the X-VERIFY hash for the S2S callback:
    SHA256(base64_payload + salt_key) + ### + salt_index

    Salt must come from `store_phonepe_credentials` for the order's store (no env fallback).
    """
    if not salt_key or not salt_key_index:
        raise ValueError(
            "PhonePe callback verification requires salt from the order's store "
            "(store_phonepe_credentials). Unknown order or missing credentials."
        )
    verification_str = base64_payload + salt_key
    hashed_str = make_hash(verification_str)
    return f"{hashed_str}###{salt_key_index}"

