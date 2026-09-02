"""REST API endpoints for Cross-Contract Intelligence, Clause Heatmap, and Portfolio Analytics."""

import uuid
from typing import Any

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from termnova.api.dependencies import get_db, get_redis_client, get_tenant_context
from termnova.intelligence.aggregator import PortfolioAggregator
from termnova.intelligence.cache import IntelligenceCache
from termnova.intelligence.schemas import (
    BenchmarkResult,
    ClauseHeatmapData,
    GapDetection,
    PortfolioSummary,
    TrendData,
    VendorScorecard,
)
from termnova.security.tenancy import TenantContext

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/intelligence", tags=["Cross-Contract Intelligence"])


@router.get(
    "/clause-heatmap",
    response_model=ClauseHeatmapData,
    summary="Get 2D Clause Presence & Risk Heatmap Matrix",
)
async def get_clause_heatmap(
    contract_type: str | None = Query(
        None, description="Filter by contract type (e.g. msa, sow, nda)"
    ),
    counterparty: str | None = Query(None, description="Filter by vendor/counterparty name"),
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis | None = Depends(get_redis_client),
    tenant: TenantContext = Depends(get_tenant_context),
) -> Any:
    """Retrieve full matrix of documents and standard clause presence/risk levels."""
    params = {"contract_type": contract_type, "counterparty": counterparty}
    cache_key = IntelligenceCache.build_key(
        "clause-heatmap", org_id=tenant.organization_id, params=params
    )

    cached = await IntelligenceCache.get(cache_key, redis_client)
    if cached:
        return cached

    aggregator = PortfolioAggregator(db)
    result = await aggregator.compute_clause_heatmap(
        contract_type=contract_type, counterparty=counterparty
    )
    await IntelligenceCache.set(cache_key, result, redis_client, ttl=300)
    return result


@router.get(
    "/vendor-scorecard/{entity_id}",
    response_model=VendorScorecard,
    summary="Get Aggregate Scorecard for a Specific Vendor/Entity",
)
async def get_vendor_scorecard_by_id(
    entity_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis | None = Depends(get_redis_client),
    tenant: TenantContext = Depends(get_tenant_context),
) -> Any:
    """Compute aggregate portfolio metrics, risk distribution, and clause coverage for a vendor."""
    cache_key = IntelligenceCache.build_key(
        "vendor-scorecard", org_id=tenant.organization_id, params={"entity_id": str(entity_id)}
    )

    cached = await IntelligenceCache.get(cache_key, redis_client)
    if cached:
        return cached

    aggregator = PortfolioAggregator(db)
    result = await aggregator.compute_vendor_scorecard(entity_id=entity_id)
    if result.contract_count == 0 and not result.entity_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vendor/Entity '{entity_id}' not found in portfolio.",
        )

    await IntelligenceCache.set(cache_key, result, redis_client, ttl=300)
    return result


@router.get(
    "/vendor-scorecard",
    response_model=VendorScorecard,
    summary="Get Aggregate Scorecard by Vendor Name",
)
async def get_vendor_scorecard_by_name(
    vendor_name: str = Query(..., min_length=1, description="Vendor or counterparty name"),
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis | None = Depends(get_redis_client),
    tenant: TenantContext = Depends(get_tenant_context),
) -> Any:
    """Compute aggregate portfolio metrics for a vendor by searching their name."""
    cache_key = IntelligenceCache.build_key(
        "vendor-scorecard",
        org_id=tenant.organization_id,
        params={"vendor_name": vendor_name.lower().strip()},
    )

    cached = await IntelligenceCache.get(cache_key, redis_client)
    if cached:
        return cached

    aggregator = PortfolioAggregator(db)
    result = await aggregator.compute_vendor_scorecard(entity_name=vendor_name)
    await IntelligenceCache.set(cache_key, result, redis_client, ttl=300)
    return result


@router.get(
    "/benchmark/{document_id}",
    response_model=BenchmarkResult,
    summary="Score a Contract Against Historical Portfolio Averages",
)
async def get_document_benchmark(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis | None = Depends(get_redis_client),
    tenant: TenantContext = Depends(get_tenant_context),
) -> Any:
    """Rank a specific contract against portfolio percentiles for safety and coverage."""
    cache_key = IntelligenceCache.build_key(
        "benchmark", org_id=tenant.organization_id, params={"document_id": str(document_id)}
    )

    cached = await IntelligenceCache.get(cache_key, redis_client)
    if cached:
        return cached

    aggregator = PortfolioAggregator(db)
    try:
        result = await aggregator.compute_benchmark(document_id=document_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    await IntelligenceCache.set(cache_key, result, redis_client, ttl=600)
    return result


@router.get(
    "/trends",
    response_model=TrendData,
    summary="Time-Series Trend Analysis for Portfolio Metrics",
)
async def get_portfolio_trends(
    metric: str = Query("risk", description="Metric to analyze: 'risk', 'value', 'compliance'"),
    period: str = Query("monthly", description="Period granularity: 'monthly', 'quarterly'"),
    months: int = Query(12, ge=1, le=60, description="Rolling months window"),
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis | None = Depends(get_redis_client),
    tenant: TenantContext = Depends(get_tenant_context),
) -> Any:
    """Retrieve time-series risk, contract value, or compliance trends across the portfolio."""
    params = {"metric": metric, "period": period, "months": months}
    cache_key = IntelligenceCache.build_key("trends", org_id=tenant.organization_id, params=params)

    cached = await IntelligenceCache.get(cache_key, redis_client)
    if cached:
        return cached

    aggregator = PortfolioAggregator(db)
    result = await aggregator.compute_trends(metric=metric, period=period, months=months)
    await IntelligenceCache.set(cache_key, result, redis_client, ttl=900)
    return result


@router.get(
    "/gaps",
    response_model=list[GapDetection],
    summary="Detect Contracts Missing Standard Mandatory Clauses",
)
async def get_contract_gaps(
    contract_type: str | None = Query(None, description="Filter by contract type"),
    severity: str | None = Query(
        None, description="Filter by severity: 'low', 'medium', 'high', 'critical'"
    ),
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis | None = Depends(get_redis_client),
    tenant: TenantContext = Depends(get_tenant_context),
) -> Any:
    """Scan the repository for agreements missing critical baseline playbook provisions."""
    params = {"contract_type": contract_type, "severity": severity}
    cache_key = IntelligenceCache.build_key("gaps", org_id=tenant.organization_id, params=params)

    cached = await IntelligenceCache.get(cache_key, redis_client)
    if cached:
        return cached

    aggregator = PortfolioAggregator(db)
    result = await aggregator.detect_gaps(contract_type=contract_type, severity=severity)
    await IntelligenceCache.set(cache_key, result, redis_client, ttl=300)
    return result


@router.get(
    "/summary",
    response_model=PortfolioSummary,
    summary="Executive Portfolio Overview & Top Risks",
)
async def get_portfolio_summary(
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis | None = Depends(get_redis_client),
    tenant: TenantContext = Depends(get_tenant_context),
) -> Any:
    """Fetch high-level portfolio overview, total value, average risk, and critical risk alerts."""
    cache_key = IntelligenceCache.build_key("summary", org_id=tenant.organization_id)

    cached = await IntelligenceCache.get(cache_key, redis_client)
    if cached:
        return cached

    aggregator = PortfolioAggregator(db)
    result = await aggregator.compute_portfolio_summary()
    await IntelligenceCache.set(cache_key, result, redis_client, ttl=900)
    return result
