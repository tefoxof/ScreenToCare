from datetime import date, datetime, timezone
from uuid import uuid4

import local_state_store


def test_local_state_store_round_trips_workflow_types(tmp_path):
    state_path = tmp_path / "screentocare-state.json"
    expected = {
        "patients": {uuid4(): {"patient_id": uuid4()}},
        "screened_at": datetime(2026, 11, 20, tzinfo=timezone.utc),
        "date_of_birth": date(1990, 1, 2),
    }

    local_state_store.save_state(str(state_path), expected)

    assert local_state_store.load_state(str(state_path)) == expected


def test_local_state_store_returns_none_when_file_does_not_exist(tmp_path):
    assert local_state_store.load_state(str(tmp_path / "missing.json")) is None
