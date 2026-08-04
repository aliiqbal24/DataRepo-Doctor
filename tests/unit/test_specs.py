import pytest
from pydantic import ValidationError

from datarepo_doctor.domain.models import ProbeSpec


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"filters": (), "arguments": {}}, "explicitly bounded"),
        ({"selected_columns": ()}, "must not be empty"),
        ({"sort_columns": ("missing",)}, "subset"),
        ({"description": "password=hunter2"}, "secrets"),
    ],
)
def test_probe_spec_rejects_unsafe_contract(probe, updates, message):
    payload = probe.model_dump()
    payload.update(updates)
    with pytest.raises(ValidationError, match=message):
        ProbeSpec.model_validate(payload)


def test_spec_hash_is_stable(probe):
    assert probe.spec_hash == ProbeSpec.model_validate(probe.model_dump()).spec_hash
