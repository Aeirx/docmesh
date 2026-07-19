"""Ask-the-Corpus orchestration: retrieve -> ground -> generate -> verify.

Mirrors ExplanationService's discipline (rate-limit only when inference will
actually run; LLMUnavailableError degrades gracefully, never a 500) but with
two deliberate differences:

NO ANSWER CACHE. Edge explanations cache because their key space is tiny
(document pairs x models) and inputs are content-derived. Questions are
free-form natural language — effectively unbounded cardinality with near-zero
exact-repeat probability — and any persistent cache would need an invalidation
story for every upload/delete. The cost of a rare re-ask is already bounded by
the token bucket, and TanStack Query dedups literal re-submissions client-side
for free. No cache -> no new table -> no migration.

ONE SHARED TOKEN BUCKET with the explanation endpoint (app.state.llm_ratelimit):
the bucket protects one physical resource — CPU-bound llama.cpp inference,
serialized by the client's generation lock. Two buckets would let explanations
and answers stack 2x rpm_limit generations onto the same core, defeating the
limit's purpose. (An answer costs ~2x an explanation's tokens; if that ever
matters, try_acquire(cost=2.0) is the knob — not built until needed.)
"""

import time
from typing import Literal

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.ratelimit import TokenBucket
from app.llm.interface import LLMClient, LLMUnavailableError
from app.llm.qa_prompt import build_qa_messages, parse_citations, postprocess_answer
from app.schemas.ask import AskRequest, AskResponse, AskTimings, Citation
from app.schemas.search import SearchRequest, SearchResponse
from app.services.explanation_service import RateLimitedError
from app.services.search_service import SearchService

logger = get_logger(__name__)


class AnswerService:
    def __init__(
        self,
        *,
        settings: Settings,
        search: SearchService,
        llm: LLMClient | None,
        bucket: TokenBucket,
    ) -> None:
        self._settings = settings
        self._search = search
        self._llm = llm
        self._bucket = bucket

    async def ask(self, req: AskRequest) -> AskResponse:
        """Raises RateLimitedError (-> 429 via the app-level handler) only when
        a generation token was needed and the bucket is empty — the retrieval
        itself is never rate limited."""
        cfg = self._settings.ask
        started = time.perf_counter()

        # 1. Retrieve with the FULL Phase-2 pipeline — embed -> FAISS + BM25 ->
        #    RRF -> hydrate -> cross-encoder rerank. Zero duplicated ranking
        #    logic; per-stage timings come along for free.
        retrieval = await self._search.search(
            SearchRequest(query=req.question, top_k=req.top_k or cfg.top_k)
        )

        # 2. Zero hits: the model must NOT run. There is nothing to ground on,
        #    and an answer produced from nothing is parametric-knowledge
        #    hallucination by construction.
        if not retrieval.hits:
            return self._degraded(req, retrieval, started, generator="no_evidence")

        ctx = build_qa_messages(req.question, retrieval.hits, cfg)

        # 3. LLM disabled by config -> evidence-only response.
        if self._llm is None:
            return self._degraded(
                req, retrieval, started, generator="unavailable", context_chunks=len(ctx.included)
            )

        # 4. Rate limit HERE, immediately before inference — never on retrieval.
        #    The scarce resource is CPU inference, not reads.
        allowed, retry_after = self._bucket.try_acquire()
        if not allowed:
            raise RateLimitedError(retry_after)

        gen_started = time.perf_counter()
        try:
            result = await self._llm.complete(
                ctx.messages,
                max_tokens=cfg.max_tokens,
                temperature=cfg.temperature,
                top_p=cfg.top_p,
            )
        except LLMUnavailableError:
            # Model missing/broken: the retrieval is still valuable — return it
            # with an honest generator flag. Never a 500.
            return self._degraded(
                req, retrieval, started, generator="unavailable", context_chunks=len(ctx.included)
            )
        generate_ms = (time.perf_counter() - gen_started) * 1000.0

        answer = postprocess_answer(result.text)
        if not answer:
            return self._degraded(
                req, retrieval, started, generator="unavailable", context_chunks=len(ctx.included)
            )

        # 5. Verify citations against the closed in-prompt set; hallucinated
        #    markers are stripped, survivors map 1:1 onto evidence ranks.
        answer, markers = parse_citations(answer, ctx.included)
        citations = [
            Citation(
                marker=m,
                chunk_id=ctx.included[m - 1].chunk_id,
                document_id=ctx.included[m - 1].document_id,
                filename=ctx.included[m - 1].filename,
                page_start=ctx.included[m - 1].page_start,
                page_end=ctx.included[m - 1].page_end,
                section=ctx.included[m - 1].section,
            )
            for m in markers
        ]

        total_ms = (time.perf_counter() - started) * 1000.0
        logger.info(
            "answer_generated",
            model=result.model_id,
            citations=len(citations),
            context_chunks=len(ctx.included),
            generate_ms=round(generate_ms, 2),
            total_ms=round(total_ms, 2),
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )
        return AskResponse(
            question=req.question,
            answer=answer,
            generator="llm",
            model=result.model_id,
            citations=citations,
            evidence=retrieval.hits,
            context_chunks=len(ctx.included),
            timings=AskTimings(
                retrieval=retrieval.timings,
                generate_ms=round(generate_ms, 2),
                total_ms=round(total_ms, 2),
            ),
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )

    @staticmethod
    def _degraded(
        req: AskRequest,
        retrieval: SearchResponse,
        started: float,
        *,
        generator: Literal["unavailable", "no_evidence"],
        context_chunks: int = 0,
    ) -> AskResponse:
        return AskResponse(
            question=req.question,
            answer="",
            generator=generator,  # callers pass literal values; pydantic validates
            model=None,
            citations=[],
            evidence=retrieval.hits,
            context_chunks=context_chunks,
            timings=AskTimings(
                retrieval=retrieval.timings,
                generate_ms=0.0,
                total_ms=round((time.perf_counter() - started) * 1000.0, 2),
            ),
        )
