"""Edge-explanation orchestration: evidence -> cache -> LLM (or template).

A separate service, not folded into GraphService — different lifecycle
(per-request, cache-driven, rate-limited) and different dependencies (LLM,
explanation repo). It talks to repos directly rather than depending on
GraphService, avoiding service->service coupling for ~10 duplicated
hydration lines.

Generation is LAZY, on demand, firmly: on this hardware a 1.5B Q4 generation
is roughly 5-20 s of CPU; eagerly explaining every edge inside recompute would
turn a seconds-long recompute into a 10-30 minute burn, mostly for edges
nobody will ever click. Pre-warm seam (not built): a background loop calling
explain() over edges by combined_score desc — trivially addable because the
method is already fire-and-forgettable.

Concurrent duplicate generation for the same edge (two tabs): both miss,
generate sequentially under the client's gen lock, the second upsert
overwrites identically. Accepted — a per-key async lock is complexity without
a user-visible payoff on a single-user app.
"""

import time

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.ratelimit import TokenBucket
from app.graph.combiner import dominant_signal
from app.llm.interface import LLMClient, LLMUnavailableError
from app.llm.prompt import (
    MAX_ENTITIES_IN_PROMPT,
    EdgeEvidence,
    EvidencePair,
    build_messages,
    compute_cache_key,
    postprocess,
)
from app.llm.template import TemplateExplainer
from app.schemas.documents import Chunk, Document
from app.schemas.graph import (
    Edge,
    EdgeExplanation,
    EdgeExplanationCreate,
    EdgeExplanationRecord,
)
from app.storage.interfaces import (
    ChunkRepository,
    DocumentRepository,
    EdgeRepository,
    ExplanationRepository,
)

logger = get_logger(__name__)


class RateLimitedError(Exception):
    """A generation token was needed (LLM inference would run) and the bucket
    is empty. Cache hits and template renders never raise this — the scarce
    resource is CPU inference, not reads."""

    def __init__(self, retry_after_s: float) -> None:
        super().__init__(f"llm rate limit exceeded; retry after {retry_after_s:.1f}s")
        self.retry_after_s = retry_after_s


class ExplanationService:
    def __init__(
        self,
        *,
        settings: Settings,
        doc_repo: DocumentRepository,
        chunk_repo: ChunkRepository,
        edge_repo: EdgeRepository,
        explanation_repo: ExplanationRepository,
        llm: LLMClient | None,
        template: TemplateExplainer,
        bucket: TokenBucket,
    ) -> None:
        self._settings = settings
        self._docs = doc_repo
        self._chunks = chunk_repo
        self._edges = edge_repo
        self._explanations = explanation_repo
        self._llm = llm  # None -> template only (settings.llm.enabled=False)
        self._template = template
        self._bucket = bucket

    async def explain(
        self, doc_a: str, doc_b: str, *, refresh: bool = False
    ) -> EdgeExplanation | None:
        """None -> no such edge (the route 404s). Raises RateLimitedError when a
        token-bucket token is needed (LLM generation) and unavailable."""
        edge = await self._edges.get(doc_a, doc_b)  # repo canonicalizes order
        if edge is None:
            return None
        ev = await self._build_evidence(edge)

        if self._llm is not None:
            key = compute_cache_key(self._llm.model_id, edge, ev)
            if not refresh:
                cached = await self._explanations.get_by_cache_key(key)
                if cached is not None:
                    return self._wire(edge, cached, cached_hit=True)
            # The rate limit is enforced HERE, immediately before inference —
            # never on cache hits or template renders (deliberate: 429ing a user
            # who clicks through ten already-cached edges is punitive theater).
            allowed, retry_after = self._bucket.try_acquire()
            if not allowed:
                raise RateLimitedError(retry_after)
            started = time.perf_counter()
            try:
                cfg = self._settings.llm
                result = await self._llm.complete(
                    build_messages(ev),
                    max_tokens=cfg.max_tokens,
                    temperature=cfg.temperature,
                    top_p=cfg.top_p,
                )
            except LLMUnavailableError:
                pass  # degrade to the template path below; never a 500
            else:
                text = postprocess(result.text)
                if text:  # empty output is a generation failure -> template
                    record = await self._explanations.upsert(
                        EdgeExplanationCreate(
                            cache_key=key,
                            edge_id=edge.id,
                            model=result.model_id,
                            explanation=text,
                            input_tokens=result.input_tokens,
                            output_tokens=result.output_tokens,
                        )
                    )
                    duration_ms = round((time.perf_counter() - started) * 1000.0, 2)
                    logger.info(
                        "explanation_generated",
                        edge_id=edge.id,
                        model=result.model_id,
                        duration_ms=duration_ms,
                        input_tokens=result.input_tokens,
                        output_tokens=result.output_tokens,
                    )
                    return self._wire(edge, record, cached_hit=False, duration_ms=duration_ms)

        return await self._template_explanation(edge, ev, refresh=refresh)

    async def _template_explanation(
        self, edge: Edge, ev: EdgeEvidence, *, refresh: bool
    ) -> EdgeExplanation:
        key = compute_cache_key(TemplateExplainer.model_id, edge, ev)
        if not refresh:
            cached = await self._explanations.get_by_cache_key(key)
            if cached is not None:
                return self._wire(edge, cached, cached_hit=True)
        started = time.perf_counter()
        record = await self._explanations.upsert(
            EdgeExplanationCreate(
                cache_key=key,
                edge_id=edge.id,
                model=TemplateExplainer.model_id,
                explanation=self._template.render(ev),
            )
        )
        duration_ms = round((time.perf_counter() - started) * 1000.0, 2)
        logger.info("explanation_generated", edge_id=edge.id, model="template")
        return self._wire(edge, record, cached_hit=False, duration_ms=duration_ms)

    async def _build_evidence(self, edge: Edge) -> EdgeEvidence:
        doc_a = await self._docs.get(edge.source_doc_id)
        doc_b = await self._docs.get(edge.target_doc_id)
        # Same hydration rule as GraphService.get_edge_detail: get_many preserves
        # order and drops missing ids, so a vanished chunk skips its pair.
        chunk_ids = [cid for p in edge.top_pairs for cid in (p.a, p.b)]
        chunks = {c.id: c for c in await self._chunks.get_many(chunk_ids)}
        pairs = sorted(
            (
                EvidencePair(
                    text_a=chunks[p.a].text,
                    text_b=chunks[p.b].text,
                    similarity=p.sim,
                    where_a=_where(chunks[p.a]),
                    where_b=_where(chunks[p.b]),
                )
                for p in edge.top_pairs
                if p.a in chunks and p.b in chunks
            ),
            key=lambda p: -p.similarity,
        )
        return EdgeEvidence(
            doc_a=_display_name(doc_a, edge.source_doc_id),
            doc_b=_display_name(doc_b, edge.target_doc_id),
            dominant_signal=dominant_signal(
                edge.semantic_score, edge.entity_score, edge.topic_score, self._settings.graph
            ),
            semantic_score=edge.semantic_score,
            entity_score=edge.entity_score,
            topic_score=edge.topic_score,
            combined_score=edge.combined_score,
            # Capped here, not just in the prompt: the cap participates in the
            # cache key (an entity beyond the top 6 can't change the output).
            shared_entities=edge.shared_entities[:MAX_ENTITIES_IN_PROMPT],
            pairs=pairs,
        )

    @staticmethod
    def _wire(
        edge: Edge,
        record: EdgeExplanationRecord,
        *,
        cached_hit: bool,
        duration_ms: float | None = None,
    ) -> EdgeExplanation:
        if cached_hit:
            logger.info("explanation_cache_hit", edge_id=edge.id, model=record.model)
        return EdgeExplanation(
            edge_id=edge.id,
            source=edge.source_doc_id,
            target=edge.target_doc_id,
            explanation=record.explanation,
            generator="template" if record.model == TemplateExplainer.model_id else "llm",
            model=record.model,
            cached=cached_hit,
            generated_at=record.created_at,
            input_tokens=record.input_tokens,
            output_tokens=record.output_tokens,
            duration_ms=duration_ms,
        )


def _display_name(doc: Document | None, fallback: str) -> str:
    if doc is None:  # deleted mid-request; the id still names the node
        return fallback
    return doc.title or doc.original_filename


def _where(chunk: Chunk) -> str | None:
    if chunk.section:
        return f'section "{chunk.section}"'
    if chunk.page_start is not None:
        return f"page {chunk.page_start}"
    return None
