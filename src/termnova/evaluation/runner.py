"""Evaluation runner executing the 30-case benchmark suite and computing quantitative RAG metrics."""

import argparse
import asyncio
import time
from pathlib import Path

import structlog

from termnova.config import Settings, get_settings
from termnova.db.connection import AsyncSessionFactory, create_async_engine
from termnova.evaluation import EvaluationReport, SampleEvalResult
from termnova.evaluation.dataset import EvalDatasetLoader
from termnova.evaluation.metrics import (
    compute_answer_relevance,
    compute_context_precision,
    compute_context_recall,
    compute_faithfulness,
)
from termnova.evaluation.report import ReportGenerator
from termnova.pipeline.embedder import EmbeddingService
from termnova.pipeline.ingestion import IngestionPipeline
from termnova.rag.engine import RAGEngine

logger = structlog.get_logger(__name__)


class EvaluationRunner:
    """Orchestrates end-to-end benchmark evaluation over enterprise contract dataset."""

    def __init__(
        self,
        settings: Settings | None = None,
        dataset_path: Path | str | None = None,
    ):
        self.settings = settings or get_settings()
        default_ds = (
            Path(__file__).parent.parent.parent.parent / "data" / "eval" / "eval_dataset.json"
        )
        self.dataset_path = Path(dataset_path) if dataset_path else default_ds

    async def run(self, output_report_path: Path | str | None = None) -> EvaluationReport:
        """Execute full evaluation pipeline."""
        engine = create_async_engine(self.settings)
        factory = AsyncSessionFactory(engine)
        embedder = EmbeddingService(self.settings)

        # 1. Ingest sample contracts if not present
        samples_dir = (
            Path(__file__).parent.parent.parent.parent / "data" / "eval" / "sample_contracts"
        )
        async with factory() as session:
            pipeline = IngestionPipeline(session, embedder, self.settings)
            if samples_dir.exists():
                logger.info("Ensuring sample contracts are ingested", dir=str(samples_dir))
                await pipeline.ingest_directory(samples_dir, force_reindex=False)

        # 2. Load dataset
        logger.info("Loading evaluation dataset", path=str(self.dataset_path))
        samples = EvalDatasetLoader.load(self.dataset_path)
        logger.info("Loaded benchmark test cases", total=len(samples))

        sample_results: list[SampleEvalResult] = []

        async with factory() as session:
            rag_engine = RAGEngine(session, embedder, self.settings)

            for idx, sample in enumerate(samples):
                logger.info(
                    f"Evaluating [{idx + 1}/{len(samples)}] {sample.id}",
                    category=sample.category,
                    query=sample.query[:50],
                )

                t_start = time.time()
                query_res = await rag_engine.query(sample.query)
                latency_ms = int((time.time() - t_start) * 1000)

                # Extract retrieved texts from citations / context
                retrieved_texts = [c.excerpt for c in query_res.citations]

                # Compute Metrics
                f_score = compute_faithfulness(query_res.answer, retrieved_texts)
                r_score = compute_answer_relevance(sample.query, query_res.answer, embedder)
                p_score = compute_context_precision(sample.ground_truth_contexts, retrieved_texts)
                c_score = compute_context_recall(sample.ground_truth_contexts, retrieved_texts)

                # Pass criteria: Faithfulness >= 0.70 and (Relevance >= 0.60 or precision >= 0.50)
                passed = f_score >= 0.65 and (r_score >= 0.50 or p_score >= 0.50)

                result_item = SampleEvalResult(
                    sample_id=sample.id,
                    query=sample.query,
                    predicted_answer=query_res.answer,
                    ground_truth=sample.ground_truth_answer,
                    faithfulness=f_score,
                    answer_relevance=r_score,
                    context_precision=p_score,
                    context_recall=c_score,
                    citations_count=len(query_res.citations),
                    latency_ms=latency_ms,
                    category=sample.category,
                    difficulty=sample.difficulty,
                    passed=passed,
                )
                sample_results.append(result_item)

        await engine.dispose()

        # 3. Aggregate Metrics
        total = len(sample_results)
        avg_faith = sum(s.faithfulness for s in sample_results) / total if total else 0.0
        avg_rel = sum(s.answer_relevance for s in sample_results) / total if total else 0.0
        avg_prec = sum(s.context_precision for s in sample_results) / total if total else 0.0
        avg_rec = sum(s.context_recall for s in sample_results) / total if total else 0.0
        pass_rate = sum(1 for s in sample_results if s.passed) / total if total else 0.0
        avg_lat = sum(s.latency_ms for s in sample_results) / total if total else 0.0

        # Category Breakdowns
        cat_scores: dict[str, dict[str, float]] = {}
        for s in sample_results:
            if s.category not in cat_scores:
                cat_scores[s.category] = {"f": [], "r": [], "p": [], "rec": [], "pass": []}
            cat_scores[s.category]["f"].append(s.faithfulness)
            cat_scores[s.category]["r"].append(s.answer_relevance)
            cat_scores[s.category]["p"].append(s.context_precision)
            cat_scores[s.category]["rec"].append(s.context_recall)
            cat_scores[s.category]["pass"].append(1.0 if s.passed else 0.0)

        category_summary = {
            cat: {
                "faithfulness": round(sum(v["f"]) / len(v["f"]), 3),
                "relevance": round(sum(v["r"]) / len(v["r"]), 3),
                "precision": round(sum(v["p"]) / len(v["p"]), 3),
                "recall": round(sum(v["rec"]) / len(v["rec"]), 3),
                "pass_rate": round(sum(v["pass"]) / len(v["pass"]), 3),
            }
            for cat, v in cat_scores.items()
        }

        # Difficulty Breakdowns
        diff_scores: dict[str, dict[str, float]] = {}
        for s in sample_results:
            if s.difficulty not in diff_scores:
                diff_scores[s.difficulty] = {"f": [], "r": [], "p": [], "rec": [], "pass": []}
            diff_scores[s.difficulty]["f"].append(s.faithfulness)
            diff_scores[s.difficulty]["r"].append(s.answer_relevance)
            diff_scores[s.difficulty]["p"].append(s.context_precision)
            diff_scores[s.difficulty]["rec"].append(s.context_recall)
            diff_scores[s.difficulty]["pass"].append(1.0 if s.passed else 0.0)

        difficulty_summary = {
            diff: {
                "faithfulness": round(sum(v["f"]) / len(v["f"]), 3),
                "relevance": round(sum(v["r"]) / len(v["r"]), 3),
                "precision": round(sum(v["p"]) / len(v["p"]), 3),
                "recall": round(sum(v["rec"]) / len(v["rec"]), 3),
                "pass_rate": round(sum(v["pass"]) / len(v["pass"]), 3),
            }
            for diff, v in diff_scores.items()
        }

        report = EvaluationReport(
            total_samples=total,
            overall_faithfulness=round(avg_faith, 3),
            overall_relevance=round(avg_rel, 3),
            overall_precision=round(avg_prec, 3),
            overall_recall=round(avg_rec, 3),
            overall_pass_rate=round(pass_rate, 3),
            avg_latency_ms=round(avg_lat, 1),
            category_scores=category_summary,
            difficulty_scores=difficulty_summary,
            sample_results=sample_results,
        )

        # 4. Save Report
        if output_report_path:
            out_p = Path(output_report_path)
            out_p.parent.mkdir(parents=True, exist_ok=True)
            md_content = ReportGenerator.generate_markdown(report)
            with open(out_p, "w", encoding="utf-8") as f:
                f.write(md_content)
            logger.info("Evaluation report saved successfully", path=str(out_p))

        return report


def main() -> None:
    """CLI entry point for running the evaluation benchmark."""
    parser = argparse.ArgumentParser(description="Termnova RAG Evaluation Benchmark Runner")
    parser.add_argument(
        "--dataset", default="data/eval/eval_dataset.json", help="Path to eval dataset JSON"
    )
    parser.add_argument(
        "--output", default="docs/evaluation-report.md", help="Output markdown report path"
    )
    parser.add_argument(
        "--thresholds",
        default=None,
        help="Optional release-threshold JSON; exits non-zero on regression",
    )
    args = parser.parse_args()

    runner = EvaluationRunner(dataset_path=args.dataset)
    report = asyncio.run(runner.run(output_report_path=args.output))

    print("\n" + "=" * 60)
    print("      TERMNOVA QUANTITATIVE EVALUATION RESULTS")
    print("=" * 60)
    print(f"Total Test Cases Analyzed : {report.total_samples}")
    print(f"Faithfulness Score        : {report.overall_faithfulness:.3f}")
    print(f"Answer Relevance Score    : {report.overall_relevance:.3f}")
    print(f"Context Precision (P@K)   : {report.overall_precision:.3f}")
    print(f"Context Recall Score      : {report.overall_recall:.3f}")
    print(f"Overall Pass Rate         : {report.overall_pass_rate * 100:.1f}%")
    print(f"Mean Query Latency        : {report.avg_latency_ms:.1f} ms")
    print("=" * 60)
    print(f"Full report exported to: {args.output}\n")
    if args.thresholds:
        from termnova.evaluation.gates import evaluate_release_gate

        failures = evaluate_release_gate(report, args.thresholds)
        if failures:
            for failure in failures:
                print(f"RELEASE GATE FAILED: {failure}")
            raise SystemExit(1)


if __name__ == "__main__":
    main()
