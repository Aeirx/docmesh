"""Ask-the-Corpus endpoint. Thin by design: validation in the Pydantic model,
orchestration in AnswerService."""

from fastapi import APIRouter, Depends

from app.api.dependencies import get_answer_service
from app.schemas.ask import AskRequest, AskResponse
from app.services.answer_service import AnswerService

router = APIRouter(prefix="/ask", tags=["ask"])


@router.post("", response_model=AskResponse, response_model_exclude_none=True)
async def ask(
    req: AskRequest,
    service: AnswerService = Depends(get_answer_service),
) -> AskResponse:
    """Synchronous by design: one bounded generation (max_tokens-capped), the
    same contract as the explanation endpoint. Token streaming would need
    LLMClient.stream() + SSE — a future seam, not a Phase 5 requirement; the
    client owns the honest loading state instead. 429 (rate_limited,
    Retry-After) when a generation token is needed and the bucket is empty."""
    return await service.ask(req)
