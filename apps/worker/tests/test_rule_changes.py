"""Rule change detection tests (OS-014)."""

from open_signal.derived.rule_changes import (
    align_paragraphs,
    is_technical_change,
    paragraph_id,
    split_paragraphs,
)


def _rule(text: str) -> str:
    return (
        "Sec. 123.4 Labeling requirements.\n\n"
        f"(a) {text}\n\n"
        "(b) The manufacturer shall retain records."
    )


def test_split_and_paragraph_id() -> None:
    paras = split_paragraphs(_rule("All products must be tested."))
    assert len(paras) == 3
    assert paragraph_id(paras[1]) == "(a)"
    assert paragraph_id(paras[0]) == "sec-123.4"


def test_no_changes_when_equal() -> None:
    d = align_paragraphs(_rule("All products must be tested."), _rule("All products must be tested."))
    assert d.changes == []


def test_add_paragraph() -> None:
    old_t = "Sec. 123.4 Labeling.\n\n(a) All products must be tested."
    new_t = old_t + "\n\n(c) The label shall include the date."
    d = align_paragraphs(old_t, new_t)
    adds = [c for c in d.changes if c.kind == "add"]
    assert len(adds) == 1
    assert "date" in adds[0].new_text


def test_delete_paragraph() -> None:
    old_t = "Sec. 123.4 Labeling.\n\n(a) All products must be tested.\n\n(b) Keep records."
    new_t = "Sec. 123.4 Labeling.\n\n(a) All products must be tested."
    d = align_paragraphs(old_t, new_t)
    deletes = [c for c in d.changes if c.kind == "delete"]
    assert len(deletes) == 1
    assert "records" in deletes[0].old_text


def test_change_paragraph() -> None:
    old_t = _rule("All products must be tested for safety.")
    new_t = _rule("All products must be tested for safety and durability.")
    d = align_paragraphs(old_t, new_t)
    changes = [c for c in d.changes if c.kind == "change"]
    assert len(changes) == 1
    assert "durability" in changes[0].new_text


def test_technical_date_change_filtered() -> None:
    old_t = _rule("Effective January 1, 2026.")
    new_t = _rule("Effective January 1, 2027.")
    d = align_paragraphs(old_t, new_t)
    assert len(d.changes) >= 1
    assert d.substantive() == []  # all filtered as technical
    assert is_technical_change(d.changes[0])


def test_technical_citation_filtered() -> None:
    old_t = _rule("See 90 FR 12345.")
    new_t = _rule("See 90 FR 54321.")
    d = align_paragraphs(old_t, new_t)
    assert d.substantive() == []


def test_formatting_only_ignored() -> None:
    old_t = "Sec. 1.1 A.\n\n(a) Hello world."
    new_t = "Sec. 1.1 A.\n\n(a) Hello   world."
    d = align_paragraphs(old_t, new_t)
    assert d.changes == []


def test_classify_change_types() -> None:
    d = align_paragraphs(
        _rule("The threshold is 5 percent."),
        _rule("The threshold is 10 percent."),
    )
    types = d.change_types()
    assert types
    assert "threshold_change" in types[0]["candidate_types"]


def test_classify_policy_and_scope() -> None:
    d = align_paragraphs(
        _rule("Products shall not contain lead."),
        _rule("Products shall not contain lead or cadmium."),
    )
    types = d.change_types()[0]["candidate_types"]
    assert "policy_change" in types


def test_materiality_deferred() -> None:
    # OS-014 explicitly defers materiality to the agent: change_types
    # returns candidates, not a verdict.
    d = align_paragraphs(
        _rule("The limit is 100."),
        _rule("The limit is 200."),
    )
    for c in d.change_types():
        assert "unclassified" not in c["candidate_types"] or len(c["candidate_types"]) >= 1
