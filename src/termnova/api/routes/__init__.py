from termnova.api.routes.analytics import router as analytics_router
from termnova.api.routes.auth import router as auth_router
from termnova.api.routes.connectors import router as connectors_router
from termnova.api.routes.desk import router as desk_router
from termnova.api.routes.documents import router as documents_router
from termnova.api.routes.enterprise_identity import router as enterprise_identity_router
from termnova.api.routes.governance import router as governance_router
from termnova.api.routes.graph import router as graph_router
from termnova.api.routes.health import router as health_router
from termnova.api.routes.inbox import router as inbox_router
from termnova.api.routes.intelligence import router as intelligence_router
from termnova.api.routes.languages import router as languages_router
from termnova.api.routes.lifecycle import router as lifecycle_router
from termnova.api.routes.negotiations import router as negotiations_router
from termnova.api.routes.operations import router as operations_router
from termnova.api.routes.organizations import router as organizations_router
from termnova.api.routes.query import router as query_router
from termnova.api.routes.triage_rules import router as triage_rules_router
from termnova.api.routes.verification import router as verification_router
from termnova.api.routes.workspaces import router as workspaces_router

__all__ = [
    "health_router",
    "auth_router",
    "connectors_router",
    "desk_router",
    "query_router",
    "documents_router",
    "enterprise_identity_router",
    "analytics_router",
    "graph_router",
    "governance_router",
    "workspaces_router",
    "inbox_router",
    "triage_rules_router",
    "verification_router",
    "negotiations_router",
    "organizations_router",
    "operations_router",
    "intelligence_router",
    "lifecycle_router",
    "languages_router",
]
