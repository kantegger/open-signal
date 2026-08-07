"""US rule status mapping tests (OS-013)."""
from datetime import date

import pytest
from open_signal.sources.us_rule_status import (
    apply_transition,
    load_ontology,
    map_document_status,
    transition_allowed,
    validate_status_id,
)


def _doc(**kw) -> dict:
    base = {"type": "Rule", "document_number": "2026-00001", "title": "T"}
    base.update(kw)
    return base


def test_ontology_loads() -> None:
    o = load_ontology()
    assert len(o["statuses"]) == 7
    assert {s["id"] for s in o["statuses"]} >= {
        "proposed", "withdrawn", "final", "effective", "partially_effective", "amended", "revoked",
    }


def test_proposed_rule() -> None:
    assert map_document_status(_doc(type="Proposed Rule")) == "proposed"


def test_withdrawal() -> None:
    assert map_document_status(_doc(type="Withdrawal")) == "withdrawn"


def test_final_rule_future_effective() -> None:
    now = date(2026, 8, 7)
    doc = _doc(type="Rule", effective_date="2026-12-01")
    assert map_document_status(doc, now=now) == "final"


def test_effective_rule_past_effective() -> None:
    now = date(2026, 8, 7)
    doc = _doc(type="Rule", effective_date="2026-01-15")
    assert map_document_status(doc, now=now) == "effective"


def test_partial_effectiveness_text_signal() -> None:
    doc = _doc(type="Rule", effective_date="2026-12-01", abstract="Sections take effect on different dates.")
    assert map_document_status(doc, now=date(2026, 8, 7)) == "partially_effective"


def test_partial_effectiveness_multiple_dates() -> None:
    doc = _doc(type="Rule", dates=["2026-08-01", "2027-01-01"])
    assert map_document_status(doc, now=date(2026, 8, 7)) == "partially_effective"


def test_correction_maps_to_amended() -> None:
    assert map_document_status(_doc(type="Correction")) == "amended"


def test_transition_allowed() -> None:
    assert transition_allowed("proposed", "final")
    assert transition_allowed("final", "effective")
    assert transition_allowed("effective", "amended")
    assert transition_allowed("effective", "revoked")
    assert not transition_allowed("proposed", "revoked")
    assert not transition_allowed("final", "withdrawn")


def test_apply_transition_validates() -> None:
    assert apply_transition("proposed", "final") == "final"
    with pytest.raises(Exception):
        apply_transition("proposed", "revoked")
    with pytest.raises(Exception):
        apply_transition("proposed", "no-such-status")


def test_validate_status_id() -> None:
    assert validate_status_id("effective")
    assert not validate_status_id("whatever")
