import json

from datarepo_doctor.app import _safe_spec


def test_api_spec_shows_query_code_but_omits_raw_query_structures(probe):
    payload = _safe_spec(probe)
    encoded = json.dumps(payload)
    assert "filters" not in payload
    assert "arguments" not in payload
    assert "doctor_reader" in encoded
    assert "database.table" in payload["query_code"]
    assert "product_id" in encoded
    assert "00001" in encoded  # Current demo query literals are public.
    assert "password" not in encoded.lower()
