"""Deterministic extraction rules remain conservative and reproducible."""

from termnova.facts.extractor import extract_candidates


def test_extracts_payment_due_rule_and_amount():
    facts = extract_candidates("Customer shall pay each $50,000 invoice within 30 days.")

    payment = next(fact for fact in facts if fact.fact_type == "obligation.payment")
    assert payment.actor == "Customer"
    assert str(payment.monetary_value) == "50000"
    assert payment.currency == "USD"
    assert payment.due_rule == {"offset_days": 30, "source_phrase": "30 days"}


def test_extracts_high_impact_renewal_notice_and_service_credit():
    facts = extract_candidates(
        "This Order automatically renews unless Customer gives 60 days notice; "
        "a 10% service credit applies."
    )

    assert {fact.fact_type for fact in facts} == {
        "entitlement.renewal",
        "deadline.notice_window",
        "entitlement.service_credit",
    }
    assert all(fact.risk_level == "high" for fact in facts)


def test_does_not_create_fact_for_non_obligatory_narrative():
    assert extract_candidates("The parties discussed security during implementation.") == []
