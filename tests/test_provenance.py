"""Tests for provenance pass-through (ADR-019, ADR-037)."""

from dataclasses import FrozenInstanceError

import pytest

from mira.fabric.provenance import (
    Provenance,
    ProvenancedResult,
    attach,
    mark_trusted,
    preserve,
)


def _prov(**overrides) -> Provenance:
    defaults = {
        "source_id": "docs-filesystem",
        "record_id": "well-a/log-0001",
        "units": "API",
        "crs": "EPSG:4326",
    }
    defaults.update(overrides)
    return Provenance(**defaults)


def test_attach_pairs_value_with_provenance():
    prov = _prov()
    result = attach({"depth": 1000.0, "gr": 45.2}, prov)

    assert isinstance(result, ProvenancedResult)
    assert result.value == {"depth": 1000.0, "gr": 45.2}
    assert result.provenance.source_id == "docs-filesystem"
    assert result.provenance.record_id == "well-a/log-0001"
    assert result.provenance.units == "API"
    assert result.provenance.crs == "EPSG:4326"


def test_source_data_is_untrusted_by_default():
    # Provenance default
    assert _prov().untrusted is True
    # ...and attach enforces it even if a caller passes untrusted=True explicitly
    result = attach([1, 2, 3], _prov(untrusted=True))
    assert result.provenance.untrusted is True


def test_attach_cannot_be_used_to_silently_clear_untrusted():
    # A caller cannot launder data simply by attaching: the untrusted default
    # holds unless provenance was already explicitly cleared.
    result = attach("rows", _prov())
    assert result.provenance.untrusted is True


def test_provenance_survives_a_transform():
    source = attach([1, 2, 3], _prov(units="m"))

    transformed = preserve(source, lambda rows: [r * 2 for r in rows])

    assert transformed.value == [2, 4, 6]
    # Provenance carried through verbatim.
    assert transformed.provenance == source.provenance
    assert transformed.provenance.units == "m"


def test_untrusted_flag_survives_a_transform():
    source = attach({"x": 1}, _prov())
    assert source.provenance.untrusted is True

    transformed = preserve(source, lambda d: {**d, "y": 2})

    # Transforming source data does not launder it.
    assert transformed.provenance.untrusted is True
    assert transformed.value == {"x": 1, "y": 2}


def test_provenance_survives_a_chain_of_transforms():
    source = attach(10, _prov(record_id="rec-42"))

    step1 = preserve(source, lambda n: n + 5)
    step2 = preserve(step1, lambda n: n * 3)

    assert step2.value == 45
    assert step2.provenance.record_id == "rec-42"
    assert step2.provenance.untrusted is True


def test_mark_trusted_is_the_only_escape_hatch():
    source = attach("rows", _prov())
    assert source.provenance.untrusted is True

    cleared = mark_trusted(source)

    assert cleared.provenance.untrusted is False
    assert cleared.value == "rows"
    # Original is unchanged (frozen / immutable).
    assert source.provenance.untrusted is True


def test_records_are_immutable():
    prov = _prov()
    with pytest.raises(FrozenInstanceError):
        prov.untrusted = False  # type: ignore[misc]
