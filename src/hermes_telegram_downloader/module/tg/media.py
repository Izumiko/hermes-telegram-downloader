PLACEHOLDER_FILE_NAME = "获取文件信息中..."


def media_filename(message) -> str | None:
    file_obj = getattr(message, "file", None)
    name = getattr(file_obj, "name", None)
    if name:
        return name
    for key in ("document", "video", "audio", "photo"):
        obj = getattr(message, key, None)
        if obj is None:
            continue
        name = getattr(obj, "file_name", None)
        if name:
            return name
        for attr in getattr(obj, "attributes", None) or []:
            name = getattr(attr, "file_name", None)
            if name:
                return name
    return None


def resolve_result_file_name(existing_name, message) -> str:
    if existing_name and existing_name != PLACEHOLDER_FILE_NAME:
        return existing_name
    name = media_filename(message)
    if name:
        return name
    return str(getattr(message, "id", "") or "file")
