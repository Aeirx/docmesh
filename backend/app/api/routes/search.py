"""Search endpoint. Thin by design: validation is entirely in the Pydantic model,
orchestration is entirely in the service."""

from fastapi import APIRouter, Depends

from app.api.dependencies import get_search_service
from app.schemas.search import SearchRequest, SearchResponse
from app.services.search_service import SearchService

router = APIRouter(prefix="/search", tags=["search"])


@router.post("", response_model=SearchResponse, response_model_exclude_none=True)
async def search(
    req: SearchRequest,
    service: SearchService = Depends(get_search_service),
) -> SearchResponse:
    return await service.search(req)
