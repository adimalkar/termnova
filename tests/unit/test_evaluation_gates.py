"""Release-quality threshold tests."""

import json

from termnova.evaluation import EvaluationReport
from termnova.evaluation.gates import evaluate_release_gate


def _report(**overrides) -> EvaluationReport:
    values = {
        "total_samples": 30,
        "overall_faithfulness": 0.8,
        "overall_relevance": 0.8,
        "overall_precision": 0.8,
        "overall_recall": 0.8,
        "overall_pass_rate": 0.8,
        "avg_latency_ms": 100,
        "category_scores": {},
        "difficulty_scores": {},
    }
    values.update(overrides)
    return EvaluationReport(**values)


def test_release_gate_reports_each_regression(tmp_path):
    thresholds = tmp_path / "thresholds.json"
    thresholds.write_text(
        json.dumps(
            {
                "minimum_samples": 30,
                "minimum_overall": {"faithfulness": 0.7, "context_recall": 0.7},
            }
        )
    )
    failures = evaluate_release_gate(
        _report(total_samples=10, overall_faithfulness=0.5), thresholds
    )
    assert len(failures) == 2


def test_release_gate_accepts_qualified_report(tmp_path):
    thresholds = tmp_path / "thresholds.json"
    thresholds.write_text(
        json.dumps({"minimum_samples": 30, "minimum_overall": {"pass_rate": 0.75}})
    )
    assert evaluate_release_gate(_report(), thresholds) == []
