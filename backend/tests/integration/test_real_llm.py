"""Real local-LLM generation — slow tier only.

First run downloads the ~1 GB Qwen2.5-1.5B-Instruct Q4_K_M GGUF into the
repo-local data/models/ (NOT a tmp_path, so the download is paid once). Skips
cleanly when llama_cpp is not importable or the model cannot load."""

import time
from pathlib import Path

import pytest

from app.core.config import LLMSettings

_MODELS_DIR = Path(__file__).resolve().parents[2] / "data" / "models"


@pytest.mark.slow
async def test_real_generation_over_edge_prompt() -> None:
    pytest.importorskip("llama_cpp")
    from app.llm.interface import ChatMessage, LLMUnavailableError
    from app.llm.local_llama import LocalLlamaClient
    from app.llm.prompt import EdgeEvidence, EvidencePair, build_messages, postprocess
    from app.schemas.graph import SharedEntity

    ev = EdgeEvidence(
        doc_a="zephyrium-product.txt",
        doc_b="zephyrium-review.txt",
        dominant_signal="entity",
        semantic_score=0.61,
        entity_score=0.74,
        topic_score=0.33,
        combined_score=0.59,
        shared_entities=[
            SharedEntity(text="zephyrium corporation", label="ORG", idf=1.1, count_a=2, count_b=2)
        ],
        pairs=[
            EvidencePair(
                text_a=(
                    "Zephyrium Corporation announced a quantum encryption product. "
                    "Research at Zephyrium Corporation focuses on lattice cryptography, "
                    "secure key exchange, and encryption performance for cloud workloads."
                ),
                text_b=(
                    "A security review of Zephyrium Corporation examined lattice "
                    "cryptography weaknesses. Zephyrium Corporation ships encryption "
                    "libraries implementing secure key exchange for cloud workloads."
                ),
                similarity=0.83,
            )
        ],
    )

    cfg = LLMSettings()
    client = LocalLlamaClient(cfg, _MODELS_DIR)
    messages: list[ChatMessage] = build_messages(ev)
    started = time.perf_counter()
    try:
        result = await client.complete(
            messages,
            max_tokens=cfg.max_tokens,
            temperature=cfg.temperature,
            top_p=cfg.top_p,
        )
    except LLMUnavailableError as exc:
        pytest.skip(f"local model unavailable: {exc}")
    finally:
        client.close()
    elapsed_s = time.perf_counter() - started

    text = postprocess(result.text)
    assert text, "real model produced empty output"
    assert result.input_tokens > 0
    assert result.model_id == "qwen2.5-1.5b-instruct-q4_k_m"
    print(  # noqa: T201 - real latency + output quality for the report
        f"\nreal_llm latency_s={elapsed_s:.1f} "
        f"in_tokens={result.input_tokens} out_tokens={result.output_tokens}\n"
        f"explanation={text!r}"
    )
