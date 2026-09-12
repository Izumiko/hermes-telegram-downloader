from telethon.errors import FileReferenceExpiredError, FloodWaitError


def wait_seconds_from_flood(err) -> int:
    return int(getattr(err, "seconds", 0) or 0)


def is_file_ref_expired(err) -> bool:
    return isinstance(err, FileReferenceExpiredError)


def is_flood_wait(err) -> bool:
    return isinstance(err, FloodWaitError)
