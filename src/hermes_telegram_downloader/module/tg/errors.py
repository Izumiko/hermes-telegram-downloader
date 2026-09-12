import time

from telethon.errors import FileReferenceExpiredError, FloodWaitError

_unified_flood_wait = {"until": 0.0, "reason": ""}


def wait_seconds_from_flood(err) -> int:
    return int(getattr(err, "seconds", 0) or 0)


def is_file_ref_expired(err) -> bool:
    return isinstance(err, FileReferenceExpiredError)


def is_flood_wait(err) -> bool:
    return isinstance(err, FloodWaitError)


def is_flood_wait_active() -> bool:
    return time.time() < _unified_flood_wait["until"]


def get_flood_wait_remaining() -> float:
    return max(0.0, _unified_flood_wait["until"] - time.time())


def set_flood_wait(seconds: float, reason: str = ""):
    _unified_flood_wait["until"] = time.time() + max(0.0, float(seconds))
    _unified_flood_wait["reason"] = reason
