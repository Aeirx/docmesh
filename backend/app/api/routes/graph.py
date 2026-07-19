"""Graph endpoints. Thin by design: the service owns scoring and assembly.

POST /recompute is an addition beyond the phase brief (flagged in the design):
without it, changing scoring weights would require uploading a document to
refresh the graph. It awaits the recompute — seconds at this corpus scale, so a
synchronous 200 is simpler and more honest than a job-id dance."""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import get_explanation_service, get_graph_service
from app.schemas.graph import (
    EdgeDetail,
    EdgeExplanation,
    GraphRecomputeResult,
    GraphResponse,
)
from app.services.explanation_service import ExplanationService
from app.services.graph_service import GraphService

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("", response_model=GraphResponse, response_model_exclude_none=True)
async def get_graph(
    query: str | None = Query(None, max_length=1000),
    service: GraphService = Depends(get_graph_service),
) -> GraphResponse:
    return await service.get_graph(query)


@router.get("/edges/{source}/{target}", response_model=EdgeDetail)
async def get_edge_detail(
    source: str,
    target: str,
    service: GraphService = Depends(get_graph_service),
) -> EdgeDetail:
    # Either order is accepted — canonical source<target ordering is a storage
    # concern, not a client concern (the repo sorts before lookup).
    detail = await service.get_edge_detail(source, target)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"No edge between {source} and {target}")
    return detail


@router.get("/edges/{source}/{target}/explanation", response_model=EdgeExplanation)
async def get_edge_explanation(
    source: str,
    target: str,
    refresh: bool = Query(False),
    service: ExplanationService = Depends(get_explanation_service),
) -> EdgeExplanation:
    """GET despite generate-on-miss: the client asks for "the explanation of
    this edge" — a derived, cacheable representation; generation is a cache-fill
    implementation detail (a CDN cold miss). Repeat-safe by cache key;
    ?refresh=true is the deliberate regenerate knob. Synchronous, no streaming —
    one bounded generation (max_tokens-capped); if streaming ever matters,
    LLMClient grows a stream() method and this becomes an SSE endpoint without
    touching the service. 429 (rate_limited) when a generation token is needed
    and the bucket is empty."""
    result = await service.explain(source, target, refresh=refresh)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No edge between {source} and {target}")
    return result


@router.post("/recompute", response_model=GraphRecomputeResult)
async def recompute_graph(
    service: GraphService = Depends(get_graph_service),
) -> GraphRecomputeResult:
    return await service.recompute(reason="manual")
