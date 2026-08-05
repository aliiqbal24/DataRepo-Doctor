import pytest

from datarepo_doctor.checks import PROBES
from datarepo_doctor.retrieval import _normalize_json_rows, query_code


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


@pytest.mark.parametrize("spec", PROBES, ids=lambda item: item.check_id)
def test_displayed_query_code_is_valid_python_and_contains_no_credentials(spec):
    code = query_code(spec)
    compile(code, f"<{spec.check_id}>", "exec")
    assert "password" not in code.lower()
    assert "secret" not in code.lower()
