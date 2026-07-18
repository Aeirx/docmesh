"""Graph endpoints. Thin by design: the service owns scoring and assembly.

POST /recompute is an addition beyond the phase brief (flagged in the design):
without it, changing scoring weights would require uploading a document to
refresh the graph. It awaits the recompute — seconds at this corpus scale, so a
synchronous 200 is simpler and more honest than a job-id dance."""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import get_graph_service
from app.schemas.graph import EdgeDetail, GraphRecomputeResult, GraphResponse
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


@router.post("/recompute", response_model=GraphRecomputeResult)
async def recompute_graph(
    service: GraphService = Depends(get_graph_service),
) -> GraphRecomputeResult:
    return await service.recompute(reason="manual")
