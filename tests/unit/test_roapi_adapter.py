import pytest

from datarepo_doctor.adapters.roapi_http import _normalize_json_rows
from datarepo_doctor.registry.probes import PROBES


def test_roapi_missing_nullable_property_is_normalized_to_null():
    spec = PROBES[1]
    decoded = [
        {
            "code": "placeholder",
            "label": "placeholder",
            "fuel_group_eia": "placeholder",
            "description": "placeholder",
        }
    ]

    rows = _normalize_json_rows(decoded, spec)

    assert rows[0]["fuel_phase"] is None


def test_roapi_missing_required_property_is_rejected():
    spec = PROBES[1]
    decoded = [{"code": "placeholder"}]

    with pytest.raises(ValueError, match="Required response column"):
        _normalize_json_rows(decoded, spec)
