# Feature Plan 5: Cross-Contract Intelligence & Clause Heatmap

> **2026 product direction:** The portfolio analytics in this document remain useful for Phase 4, but they are not a substitute for contract-family intelligence. The family experience is being reworked around effective terms, amendment precedence, scope/as-of-date resolution, conflicts, and downstream action. Use [the Contract-Family Effective-Term Workbench plan](../docs/contract-family-workbench-plan.md) as the implementation source for family behavior, and [the enterprise roadmap](../docs/control-tower-roadmap.md) for phase ordering.

## What We're Building

A **portfolio-wide analytics engine** that turns your collection of individual contracts into actionable intelligence. Instead of knowing "this contract has an uncapped liability clause," you know "47% of our contracts have uncapped liability, but only with vendors under $100K — our 3 largest vendors all have caps." Features:

1. **Clause Heatmap**: Matrix visualization — rows=contracts, columns=clause categories. Cell color shows risk level or presence/absence. See coverage gaps at a glance.
2. **Vendor Scorecard**: Aggregate metrics for any vendor across all their contracts — total value, average risk, compliance deviation, obligation fulfillment rate.
3. **Benchmark Scoring**: Score any new contract against the organization's historical portfolio. "This MSA is 23% riskier than your average MSA."
4. **Trend Analysis**: Time-series of risk scores, contract values, and compliance across the portfolio. Spot if negotiation positions are weakening over time.
5. **Gap Detection**: Identify contracts missing expected standard clauses (e.g., an MSA without a data protection clause).

## Why It Matters

When you have 200+ contracts, you cannot manually check:
- Are our liability positions consistent across vendors?
- Is a new vendor's terms worse than what we typically accept?
- Are our negotiators gradually giving away more ground?
- Which contracts are missing standard protections?

Enterprise platforms like Icertis charge $100K+/year for this capability ("Contract Intelligence"). By implementing it, Termnova goes from a search tool to a strategic decision-making platform that legal/procurement leadership actually uses.

---

## Architecture & Approach

### Data Dependencies
This feature is **read-heavy** — it aggregates data created by other phases:
- **Phase 2** (Obligations/Risk): Provides `ContractMetadata` with clause-level risk scores per document
- **Phase 3** (Clause Library): Provides the canonical clause categories and playbook rules
- **Phase 7.1** (Entity Graph): Provides entity nodes for vendor identification

### Query Strategy
All intelligence queries run against existing tables using PostgreSQL aggregations — **no separate analytics database or materialized views needed** for MVP. If performance becomes an issue at scale (>10K contracts), we can add materialized views later.

```
entity_nodes + document_entities  → vendor identification
documents + triage_results        → contract type, metadata
obligations / risk_scores (Phase 2 JSONB) → clause-level risk data
clause_templates (Phase 3)        → playbook comparison baseline
```

### Key Design Decisions
- **Pure PostgreSQL aggregation**: No Spark, no OLAP cube. SQL queries with `GROUP BY`, `jsonb_array_elements`, and window functions. Portfolio sizes are typically 100-5000 contracts — PostgreSQL handles this easily.
- **Lazy computation**: Intelligence queries are computed on-demand, not pre-materialized. Results are cached in Redis with TTL for repeated dashboard access.
- **Clause taxonomy is fixed**: Use a standard set of ~15 clause categories. This keeps the heatmap columns consistent and comparable.

---

## Sub-Phase 1: Intelligence Engine Core

### Standard Clause Taxonomy

Define the canonical clause categories used across all intelligence features:

```python
CLAUSE_CATEGORIES = [
    "liability",  # Limitation of liability, caps
    "indemnification",  # Mutual/unilateral indemnity
    "termination",  # Termination for convenience/cause, notice periods
    "payment",  # Payment terms, late fees, net terms
    "confidentiality",  # NDA-type provisions
    "ip_ownership",  # Intellectual property, work-for-hire
    "data_protection",  # Data privacy, GDPR, breach notification
    "insurance",  # Insurance requirements, minimums
    "force_majeure",  # Force majeure provisions
    "dispute_resolution",  # Arbitration, jurisdiction, venue
    "warranty",  # Warranties, disclaimers
    "non_compete",  # Non-compete, non-solicitation
    "assignment",  # Assignment, change of control
    "audit_rights",  # Right to audit, inspect
    "representations",  # Representations and warranties
]
```

### 1A. Clause Presence Analyzer

#### [NEW] `src/termnova/intelligence/clause_analyzer.py`

```python
"""Analyze clause presence and risk across the contract portfolio."""


class ClausePresenceAnalyzer:
    """Determines which standard clauses are present in each contract."""

    async def analyze_document(
        self,
        document_id: uuid.UUID,
        chunks: list[str],
    ) -> dict[str, ClausePresence]:
        """
        For each clause category, determine if it's present in this document.
        Uses two-pass approach:
        1. Keyword scan (fast): Search for category keywords in chunks
        2. LLM confirmation (if keyword found): Verify the clause exists and classify risk

        Returns: {category: ClausePresence(present, risk_level, excerpt, chunk_id)}
        """

    def _keyword_scan(self, text: str) -> dict[str, float]:
        """
        Fast keyword-based detection.
        Returns {category: confidence} for categories with keyword hits.
        Uses weighted keyword lists per category:
        - "liability": ["limitation of liability", "liability cap", "aggregate liability", "damages"]
        - "indemnification": ["indemnif", "hold harmless", "defend"]
        - etc.
        """


class ClausePresence(BaseModel):
    """Presence and risk level of a clause category in a document."""

    category: str
    present: bool
    risk_level: str | None  # "low", "medium", "high", "critical" — None if absent
    excerpt: str | None  # Key text snippet from the clause
    chunk_id: uuid.UUID | None
    confidence: float  # 0.0-1.0
```

### 1B. Portfolio Aggregator

#### [NEW] `src/termnova/intelligence/aggregator.py`

```python
"""Portfolio-wide aggregation engine for cross-contract intelligence."""


class PortfolioAggregator:
    """Computes aggregate metrics across the contract portfolio."""

    def __init__(self, session: AsyncSession, org_id: uuid.UUID):
        self.session = session
        self.org_id = org_id

    async def compute_clause_heatmap(
        self,
        filters: HeatmapFilters | None = None,
    ) -> ClauseHeatmapData:
        """
        Build the clause presence matrix.

        Returns:
            ClauseHeatmapData with:
            - rows: list of documents [{id, filename, contract_type}]
            - columns: list of clause categories
            - cells: 2D matrix of {present, risk_level, excerpt}
            - summary: per-column stats {present_count, pct, avg_risk}
        """

    async def compute_vendor_scorecard(
        self,
        entity_id: uuid.UUID,
    ) -> VendorScorecard:
        """
        Aggregate all contracts with a specific vendor/entity.

        Returns:
            VendorScorecard with:
            - entity: {name, type, alias_count}
            - contract_count: int
            - total_value: float
            - active_count: int
            - expired_count: int
            - avg_risk_score: float
            - risk_distribution: {low: N, medium: N, high: N, critical: N}
            - clause_coverage: {category: coverage_pct} — how many contracts have each clause
            - playbook_deviation: float — avg deviation from org playbook
            - obligation_fulfillment_rate: float — % of obligations met on time
            - negotiation_trend: list[{date, risk_score}] — are deals getting better or worse?
        """

    async def compute_benchmark(
        self,
        document_id: uuid.UUID,
    ) -> BenchmarkResult:
        """
        Score a single contract against portfolio averages.

        Methodology:
        1. Get this document's clause presence + risk levels
        2. Get portfolio-wide averages for same contract_type
        3. Compare: risk percentile, clause coverage percentile, value percentile
        4. Generate "better than X% of your MSAs" summary

        Returns:
            BenchmarkResult with:
            - overall_percentile: int (0-100, higher = better)
            - risk_percentile: int
            - clause_coverage_percentile: int
            - comparison_summary: str
            - category_breakdown: {category: {this_contract, portfolio_avg, delta}}
        """

    async def compute_trends(
        self,
        period: str = "monthly",  # "weekly", "monthly", "quarterly"
        metric: str = "risk",  # "risk", "value", "compliance"
        months: int = 12,
    ) -> TrendData:
        """
        Time-series aggregation.

        Returns:
            TrendData with:
            - data_points: [{period: "2025-Q3", value: 0.42, contract_count: 15}]
            - trend_direction: "improving" | "declining" | "stable"
            - change_pct: float — % change over the time window
        """

    async def detect_gaps(self) -> list[GapDetection]:
        """
        Find contracts missing expected standard clauses.

        Logic:
        1. For each contract_type, determine "expected" clauses
           (e.g., MSA should have: liability, indemnification, termination, data_protection, ip_ownership)
        2. Check each contract's clause presence against expectations
        3. Return contracts with missing expected clauses

        Returns:
            list of GapDetection: {document, missing_clauses: [str], severity: str}
        """
```

### 1C. Pydantic Response Schemas

#### [NEW] `src/termnova/intelligence/schemas.py`

```python
class HeatmapCell(BaseModel):
    present: bool
    risk_level: str | None
    excerpt: str | None


class HeatmapRow(BaseModel):
    document_id: uuid.UUID
    filename: str
    contract_type: str
    cells: dict[str, HeatmapCell]  # keyed by clause category


class HeatmapColumnSummary(BaseModel):
    category: str
    present_count: int
    total_count: int
    coverage_pct: float
    avg_risk: float | None


class ClauseHeatmapData(BaseModel):
    rows: list[HeatmapRow]
    columns: list[str]
    column_summaries: list[HeatmapColumnSummary]


class VendorScorecard(BaseModel):
    entity_name: str
    entity_type: str
    contract_count: int
    total_value: float | None
    active_count: int
    expired_count: int
    avg_risk_score: float
    risk_distribution: dict[str, int]
    clause_coverage: dict[str, float]
    playbook_deviation: float | None
    obligation_fulfillment_rate: float | None
    negotiation_trend: list[dict]


class BenchmarkResult(BaseModel):
    document_id: uuid.UUID
    overall_percentile: int
    risk_percentile: int
    clause_coverage_percentile: int
    comparison_summary: str
    category_breakdown: dict[str, dict]


class GapDetection(BaseModel):
    document_id: uuid.UUID
    filename: str
    contract_type: str
    missing_clauses: list[str]
    severity: str  # "low", "medium", "high"


class TrendDataPoint(BaseModel):
    period: str
    value: float
    contract_count: int


class TrendData(BaseModel):
    data_points: list[TrendDataPoint]
    trend_direction: str
    change_pct: float
```

### Tests for Sub-Phase 1
```
tests/unit/test_clause_analyzer.py
  - test_keyword_scan_finds_liability_clause
  - test_keyword_scan_no_false_positives
  - test_analyze_document_returns_presence_map
  - test_analyze_document_marks_absent_clauses

tests/unit/test_portfolio_aggregator.py
  - test_heatmap_returns_all_documents_and_categories
  - test_heatmap_column_summary_correct_percentages
  - test_vendor_scorecard_aggregates_correctly
  - test_vendor_scorecard_handles_single_contract
  - test_benchmark_computes_percentiles
  - test_benchmark_summary_text_generated
  - test_trends_monthly_aggregation
  - test_trends_direction_detected
  - test_gap_detection_finds_missing_clauses
  - test_gap_detection_no_gaps_for_complete_contract
```

---

## Sub-Phase 2: Caching & Performance

#### [NEW] `src/termnova/intelligence/cache.py`

```python
"""Redis caching for intelligence queries."""


class IntelligenceCache:
    """Cache expensive aggregation results with TTL."""

    CACHE_PREFIX = "ciq:intelligence"
    DEFAULT_TTL = 300  # 5 minutes

    async def get_or_compute(
        self,
        cache_key: str,
        compute_fn: Callable,
        ttl: int = DEFAULT_TTL,
    ) -> Any:
        """
        Check Redis cache first. If miss, compute and cache.
        Cache key includes org_id to prevent cross-tenant leakage.
        """

    def _build_key(self, org_id: uuid.UUID, query_type: str, params: dict) -> str:
        """Build cache key: ciq:intelligence:{org_id}:{query_type}:{params_hash}"""

    async def invalidate_org(self, org_id: uuid.UUID) -> None:
        """Invalidate all cached intelligence for an org (called on document change)."""
```

#### [MODIFY] `src/termnova/pipeline/ingestion.py`
After successful ingestion, invalidate the intelligence cache for the org so dashboards show fresh data.

### Tests for Sub-Phase 2
```
tests/unit/test_intelligence_cache.py
  - test_cache_miss_computes_and_stores
  - test_cache_hit_returns_cached_value
  - test_cache_key_includes_org_id
  - test_invalidate_org_clears_all_keys
```

---

## Sub-Phase 3: API Endpoints

#### [NEW] `src/termnova/api/routes/intelligence.py`

```python
router = APIRouter(prefix="/api/v1/intelligence", tags=["Cross-Contract Intelligence"])

GET  /clause-heatmap
    → Query: contract_type=msa, vendor={entity_id}, date_from, date_to
    → Returns clause presence matrix
    → Response: ClauseHeatmapData
    → Cached: 5 min TTL

GET  /vendor-scorecard/{entity_id}
    → Aggregate analysis for a vendor
    → Response: VendorScorecard
    → Cached: 5 min TTL

GET  /benchmark/{document_id}
    → Score this contract vs portfolio average
    → Response: BenchmarkResult
    → Cached: 10 min TTL (per document)

GET  /trends
    → Query: metric=risk|value|compliance, period=monthly|quarterly, months=12
    → Time-series data for portfolio metrics
    → Response: TrendData
    → Cached: 15 min TTL

GET  /gaps
    → Query: contract_type=msa, severity=high
    → Contracts missing expected clauses
    → Response: [GapDetection]
    → Cached: 5 min TTL

GET  /summary
    → Portfolio-wide executive summary
    → Response: {
        total_contracts, total_value, avg_risk,
        top_risks: [...], expiring_soon: N,
        compliance_score: float, trend_direction: str,
      }
    → Cached: 15 min TTL
```

### Tests for Sub-Phase 3
```
tests/integration/test_intelligence_api.py
  - test_clause_heatmap_returns_matrix
  - test_clause_heatmap_filter_by_contract_type
  - test_clause_heatmap_filter_by_vendor
  - test_vendor_scorecard_returns_aggregates
  - test_vendor_scorecard_404_for_unknown_entity
  - test_benchmark_returns_percentiles
  - test_benchmark_comparison_summary_generated
  - test_trends_returns_time_series
  - test_trends_direction_detected
  - test_gaps_returns_missing_clauses
  - test_gaps_filter_by_severity
  - test_summary_returns_portfolio_overview
  - test_intelligence_respects_org_isolation
  - test_intelligence_cached_on_second_call
```

---

## Sub-Phase 4: Frontend — Heatmap & Scorecard Visualization

#### [NEW] `src/termnova/static/js/intelligence.js`

```javascript
// Key UI components:

// 1. Clause Heatmap (Main visualization)
function renderClauseHeatmap(heatmapData) { ... }
// HTML table / CSS grid matrix:
// - Header row: clause category names (rotated 45° for space)
// - Each row: document name + colored cells
// - Cell colors: green (present, low risk), yellow (medium), red (high), dark gray (absent)
// - Hover cell → tooltip with excerpt snippet
// - Click cell → modal with full clause text
// - Column summary row at bottom: "85% coverage" bar
// Filter bar: contract type dropdown, vendor dropdown, date range

// 2. Vendor Scorecard Card
function renderVendorScorecard(scorecard) { ... }
// Card layout:
// - Header: vendor name, logo placeholder, contract count
// - Metrics grid: total value, avg risk, compliance score, fulfillment rate
// - Mini clause coverage bar chart: which clauses present across contracts
// - Negotiation trend mini line chart
// - Risk distribution donut chart (low/med/high/critical segments)

// 3. Benchmark Display
function renderBenchmark(benchmark) { ... }
// "Report card" style:
// - Overall: "78th percentile — better than 78% of your MSAs"
// - Gauge chart for overall percentile
// - Category table: category | this contract | portfolio avg | delta (green/red)
// - Comparison summary text

// 4. Trend Chart
function renderTrendChart(trendData) { ... }
// SVG line chart:
// - X-axis: time periods
// - Y-axis: metric value (risk/value/compliance)
// - Color: green when improving, red when declining
// - Trend direction indicator badge

// 5. Gap Detection List
function renderGapList(gaps) { ... }
// Table or card list:
// - Contract name, type, missing clauses (as red pill badges)
// - Severity badge (high/medium/low)
// - Action button: "Review Contract"
// - Sort by: severity, number of gaps

// 6. Executive Summary Widget
function renderPortfolioSummary(summary) { ... }
// Dashboard header widget:
// - Big numbers: total contracts, total value, avg risk
// - Mini trend sparklines for each metric
// - Top 3 risks callout
// - "N contracts expiring in 30 days" alert
```

#### [MODIFY] `src/termnova/static/index.html`
- Add "Intelligence" navigation tab
- Intelligence page layout: heatmap (full-width) + scorecard/benchmark/gaps (grid below)

#### [NEW] `src/termnova/static/css/intelligence.css`
- Heatmap matrix styling with cell colors and hover tooltips
- Vendor scorecard card with metric grid
- Benchmark gauge chart (CSS arc)
- Trend chart styling
- Gap detection table with severity badges
- All dark-mode compatible

### Tests for Sub-Phase 4
```
tests/e2e/test_intelligence_ui.py
  - test_intelligence_page_loads
  - test_heatmap_renders_with_documents
  - test_heatmap_hover_shows_tooltip
  - test_vendor_scorecard_loads_for_entity
  - test_benchmark_shows_percentile
  - test_trend_chart_renders_with_data
  - test_gap_list_shows_missing_clauses
```

---

## Integration Points

### With Phase 2 (Obligations/Risk)
- Uses risk scores stored in document metadata JSONB
- Uses obligation fulfillment data for vendor scorecard

### With Phase 3 (Clause Library)
- Uses clause categories as the canonical taxonomy for heatmap columns
- Playbook rules define "expected" clauses for gap detection

### With Phase 7.1 (Entity Graph)
- Uses `entity_nodes` and `document_entities` for vendor identification
- Vendor scorecard aggregates across all documents linked to an entity

### With Ingestion Pipeline
- Cache invalidation triggered on new document ingestion
- Clause presence analysis runs as post-ingestion step (alongside triage)

---

## Verification Checklist

- [ ] Clause presence analyzer detects standard clause categories
- [ ] Keyword scan has no false positives on test corpus
- [ ] Heatmap returns all documents × all clause categories
- [ ] Heatmap column summaries show correct percentages
- [ ] Vendor scorecard aggregates metrics across all vendor contracts
- [ ] Benchmark computes valid percentiles (0-100)
- [ ] Benchmark comparison summary is human-readable
- [ ] Trend data aggregates correctly by month/quarter
- [ ] Trend direction detection is accurate (improving/declining/stable)
- [ ] Gap detection identifies missing expected clauses
- [ ] Gap detection uses correct expectations per contract type
- [ ] Redis caching works (second request faster than first)
- [ ] Cache invalidated on new document ingestion
- [ ] All endpoints respect org isolation
- [ ] Heatmap UI renders with correct cell colors
- [ ] Vendor scorecard UI shows aggregate metrics
- [ ] `ruff check` and `ruff format --check` pass
- [ ] All unit and integration tests pass
