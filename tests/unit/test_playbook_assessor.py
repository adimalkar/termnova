"""Deterministic negotiation playbook evaluation tests."""

from termnova.comparison.playbook_assessor import evaluate_clause, language_similarity
from termnova.db.models import PlaybookClausePosition


def _position() -> PlaybookClausePosition:
    return PlaybookClausePosition(
        clause_category="liability",
        title="Liability cap",
        preferred_language="Aggregate liability will not exceed fees paid in the prior 12 months.",
        acceptable_language=[
            "Aggregate liability will not exceed two times fees paid in the prior 12 months."
        ],
        fallback_language="Aggregate liability will not exceed three times annual fees.",
        required_terms=["aggregate liability"],
        prohibited_terms=["unlimited liability"],
        similarity_threshold=0.8,
        risk_level="high",
        approval_level="executive",
    )


def test_exact_approved_positions_are_classified_and_fallback_escalates():
    position = _position()
    preferred = evaluate_clause(position.preferred_language, position)
    acceptable = evaluate_clause(position.acceptable_language[0], position)
    fallback = evaluate_clause(position.fallback_language or "", position)

    assert preferred.classification == "preferred"
    assert preferred.approval_required is False
    assert acceptable.classification == "acceptable"
    assert acceptable.approval_required is False
    assert fallback.classification == "fallback"
    assert fallback.approval_required is True
    assert fallback.approval_level == "executive"


def test_prohibited_and_missing_terms_take_priority_over_similarity():
    position = _position()
    prohibited = evaluate_clause(
        "Aggregate liability includes unlimited liability for all claims.", position
    )
    missing = evaluate_clause("Damages are capped at annual fees.", position)

    assert prohibited.classification == "prohibited"
    assert prohibited.similarity_score == 0.0
    assert missing.classification == "outside_playbook"
    assert "Missing required term" in missing.reason


def test_uncovered_category_requires_legal_review():
    result = evaluate_clause("A newly introduced exclusivity covenant.", None)

    assert result.classification == "outside_playbook"
    assert result.approval_required is True
    assert result.approval_level == "legal"
    assert result.suggested_language is None


def test_similarity_is_format_insensitive_and_deterministic():
    assert language_similarity("  Net 30\nDays ", "net 30 days") == 1.0
