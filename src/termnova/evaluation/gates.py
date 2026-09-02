"""Machine-readable release thresholds for retrieval and citation evaluation."""

import json
from pathlib import Path

from termnova.evaluation import EvaluationReport


def evaluate_release_gate(report: EvaluationReport, thresholds_path: Path | str) -> list[str]:
    thresholds = json.loads(Path(thresholds_path).read_text(encoding="utf-8"))
    failures: list[str] = []
    mapping = {
        "faithfulness": report.overall_faithfulness,
        "answer_relevance": report.overall_relevance,
        "context_precision": report.overall_precision,
        "context_recall": report.overall_recall,
        "pass_rate": report.overall_pass_rate,
    }
    for metric, minimum in thresholds["minimum_overall"].items():
        actual = mapping[metric]
        if actual < minimum:
            failures.append(f"{metric}={actual:.3f} is below {minimum:.3f}")
    if report.total_samples < thresholds.get("minimum_samples", 1):
        failures.append(
            f"total_samples={report.total_samples} is below {thresholds['minimum_samples']}"
        )
    return failures
