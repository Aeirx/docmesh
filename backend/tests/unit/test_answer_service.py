"""AnswerService orchestration with a stub retriever + FakeLLM — no app, no
models, no network. The integration tier drives the same flow over HTTP."""

import pytest

from app.core.config import Settings
from app.core.ratelimit import TokenBucket
from app.schemas.ask import AskRequest
from app.schemas.search import SearchHit, SearchResponse, SearchTimings
from app.services.answer_service import AnswerService
from app.services.explanation_service import RateLimitedError
from tests.fixtures.fakes import FakeLLM


def _hit(rank: int, text: str) -> SearchHit:
    return SearchHit(
        rank=rank,
        chunk_id=f"chunk-{rank}",
        document_id=f"doc-{rank}",
        filename=f"doc{rank}.txt",
        text=text,
        page_start=None,
        page_end=None,
        section=None,
        dense_score=0.9,
        bm25_score=1.0,
        fused_score=0.02,
        rerank_score=5.0,
        term_highlights=[],
        best_sentence=None,
    )


_TIMINGS = SearchTimings(
    embed_ms=1.0, dense_ms=1.0, bm25_ms=1.0, fuse_ms=0.1, rerank_ms=1.0, total_ms=4.1
)


class StubSearch:
    """SearchService-shaped: returns the hits it was built with."""

    def __init__(self, hits: list[SearchHit]) -> None:
        self._hits = hits
        self.requests: list = []

    async def search(self, req) -> SearchResponse:
        self.requests.append(req)
        return SearchResponse(query=req.query, hits=self._hits, timings=_TIMINGS)


def _service(hits: list[SearchHit], *, llm=None, bucket=None) -> tuple[AnswerService, FakeLLM]:
    fake = llm if llm is not None else FakeLLM()
    service = AnswerService(
        settings=Settings(env="test"),
        search=StubSearch(hits),  # type: ignore[arg-type]  # duck-typed on .search
        llm=fake,
        bucket=bucket or TokenBucket(capacity=10, refill_per_minute=60),
    )
    return service, fake


async def test_happy_path_maps_citations_onto_retrieved_chunks() -> None:
    service, fake = _service([_hit(1, "Alpha docs."), _hit(2, "Beta docs.")])
    fake.canned_text = "Alpha is a framework [1]. It is benchmarked in [2]. Bogus [9]."

    out = await service.ask(AskRequest(question="What is Alpha?"))

    assert out.generator == "llm"
    assert out.model == "fake-llm"
    assert "[9]" not in out.answer  # hallucinated marker stripped
    assert [c.marker for c in out.citations] == [1, 2]
    assert [c.chunk_id for c in out.citations] == ["chunk-1", "chunk-2"]
    assert out.context_chunks == 2
    assert len(out.evidence) == 2
    assert out.timings.total_ms >= out.timings.generate_ms >= 0
    assert out.input_tokens == 50 and out.output_tokens == 20


async def test_llm_unavailable_degrades_with_evidence_intact() -> None:
    service, fake = _service([_hit(1, "Alpha docs.")])
    fake.fail_unavailable = True

    out = await service.ask(AskRequest(question="q"))

    assert out.generator == "unavailable"
    assert out.answer == ""
    assert out.model is None
    assert len(out.evidence) == 1  # the retrieval is still returned
    assert out.context_chunks == 1


async def test_no_hits_never_runs_the_model() -> None:
    service, fake = _service([])

    out = await service.ask(AskRequest(question="q"))

    assert out.generator == "no_evidence"
    assert fake.calls == 0
    assert out.evidence == []
    assert out.context_chunks == 0


async def test_empty_bucket_raises_rate_limited_before_inference() -> None:
    bucket = TokenBucket(capacity=1, refill_per_minute=1, clock=lambda: 0.0)
    bucket.try_acquire()  # drain
    service, fake = _service([_hit(1, "text")], bucket=bucket)

    with pytest.raises(RateLimitedError) as excinfo:
        await service.ask(AskRequest(question="q"))
    assert excinfo.value.retry_after_s > 0
    assert fake.calls == 0  # the model was never touched
