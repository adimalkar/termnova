"""Organization-level request budget enforcement."""

import time

from fastapi import Depends, HTTPException, Request

from termnova.api.dependencies import get_redis_client, get_settings, get_tenant_context
from termnova.config import Settings
from termnova.security.tenancy import TenantContext


async def enforce_tenant_request_budget(
    request: Request,
    tenant: TenantContext = Depends(get_tenant_context),
    settings: Settings = Depends(get_settings),
    redis=Depends(get_redis_client),
) -> None:
    """Apply a fixed-window tenant budget; infrastructure failures degrade to telemetry-only."""
    if settings.APP_ENV.lower() == "test" or redis is None:
        return
    window = int(time.time() // 60)
    key = f"tenant-rate:{tenant.organization_id}:{window}"
    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 61)
        if count > settings.TENANT_REQUESTS_PER_MINUTE:
            raise HTTPException(status_code=429, detail="Organization request budget exceeded")
    except HTTPException:
        raise
    except Exception:
        request.state.tenant_rate_limit_degraded = True
