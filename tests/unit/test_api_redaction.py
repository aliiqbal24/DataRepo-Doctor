import json

from datarepo_doctor.api.app import _safe_spec


def test_api_spec_omits_filter_values_and_function_arguments(probe):
    payload = _safe_spec(probe, detail=True)
    encoded = json.dumps(payload)
    assert "filters" not in payload
    assert "arguments" not in payload
    assert "doctor_reader" in encoded
    assert "product_id" in encoded  # schema names are safe
    assert "00001" not in encoded
