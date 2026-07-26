"""record_list rows must obey the same rules as scalar config items.

The row-cleaning path used to carry its own stripped-down coercion: only
int/float/bool, silently returning the raw string on failure, with no
`select` choice check and no min/max/validators. A bad `ai.models` row was
accepted verbatim and only blew up much later, as a ValueError inside the
AI router mid-conversation.
"""
from __future__ import annotations

import pytest

from configs.backends import _clean_payload
from configs.types import ConfigRecord, record_item


def _record():
    return ConfigRecord(
        name="model_declaration",
        label="Modèle",
        fields=(
            record_item(key="internal_name", type="str", label="Nom"),
            record_item(key="provider", type="select", label="Fournisseur",
                        choices=("claude", "openai")),
            record_item(key="temperature", type="float", label="Température",
                        default=0.7, min=0.0, max=2.0),
        ),
    )


class TestRowCoercion:

    def test_numeric_string_is_coerced(self):
        cleaned, _ = _clean_payload(_record(), {
            "internal_name": "fast", "provider": "claude", "temperature": "0.4",
        })
        assert cleaned["temperature"] == pytest.approx(0.4)
        assert isinstance(cleaned["temperature"], float)

    def test_non_numeric_temperature_is_rejected(self):
        from configs.service import ValidationError

        with pytest.raises(ValidationError):
            _clean_payload(_record(), {
                "internal_name": "fast", "provider": "claude",
                "temperature": "hot",
            })

    def test_out_of_range_temperature_is_rejected(self):
        from configs.service import ValidationError

        with pytest.raises(ValidationError):
            _clean_payload(_record(), {
                "internal_name": "fast", "provider": "claude",
                "temperature": 9.0,
            })

    def test_unknown_provider_is_rejected(self):
        from configs.service import ValidationError

        with pytest.raises(ValidationError):
            _clean_payload(_record(), {
                "internal_name": "fast", "provider": "anthropicc",
                "temperature": 0.5,
            })

    def test_valid_row_passes(self):
        cleaned, encrypted = _clean_payload(_record(), {
            "internal_name": "smart", "provider": "openai", "temperature": 1.2,
        })
        assert cleaned["provider"] == "openai"
        assert encrypted == []

    def test_missing_field_falls_back_to_default(self):
        cleaned, _ = _clean_payload(_record(), {
            "internal_name": "x", "provider": "claude",
        })
        assert cleaned["temperature"] == pytest.approx(0.7)

    def test_no_record_schema_passes_payload_through(self):
        cleaned, encrypted = _clean_payload(None, {"anything": 1})
        assert cleaned == {"anything": 1}
        assert encrypted == []

    def test_row_cleaning_shares_the_service_implementation(self):
        # Two divergent copies is how one of them ends up skipping validation.
        from configs import backends, service
        assert backends._coerce is service._coerce
        assert backends._validate is service._validate
