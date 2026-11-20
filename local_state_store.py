import json
import os
import tempfile
from datetime import date, datetime
from uuid import UUID


def _encode(value):
    if isinstance(value, UUID):
        return {"__type__": "uuid", "value": str(value)}
    if isinstance(value, datetime):
        return {"__type__": "datetime", "value": value.isoformat()}
    if isinstance(value, date):
        return {"__type__": "date", "value": value.isoformat()}
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            return {
                "__type__": "mapping",
                "items": [[_encode(key), _encode(item)] for key, item in value.items()]
            }
        return {key: _encode(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(item) for item in value]
    return value


def _decode(value):
    if isinstance(value, dict):
        value_type = value.get("__type__")
        if value_type == "uuid":
            return UUID(value["value"])
        if value_type == "datetime":
            return datetime.fromisoformat(value["value"])
        if value_type == "date":
            return date.fromisoformat(value["value"])
        if value_type == "mapping":
            return {_decode(key): _decode(item) for key, item in value["items"]}
        return {key: _decode(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode(item) for item in value]
    return value


def load_state(path):
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as state_file:
        return _decode(json.load(state_file))


def save_state(path, state):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=directory,
            prefix=".screentocare-state-",
            suffix=".tmp",
            delete=False
        ) as state_file:
            temporary_path = state_file.name
            json.dump(_encode(state), state_file, ensure_ascii=False, separators=(",", ":"))
            state_file.flush()
            os.fsync(state_file.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.remove(temporary_path)
