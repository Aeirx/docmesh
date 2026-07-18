"""Entity overlap: spaCy NER extraction + IDF-weighted Jaccard scoring.

WHY weighted and not raw overlap: unweighted overlap saturates on generic
entities — every tech document shares "Google" or "USA", so raw Jaccard measures
genre, not connection. Weighting each entity by corpus rarity makes a shared
"DINOv3" (rare) worth several times a shared "Microsoft" (everywhere), which is
what a human means by "these documents are connected".

Two classes with different lifecycles:
- EntityExtractor: lazy spaCy singleton, lives on app.state, patched by the fast
  test tier exactly like DenseEmbedder.
- EntityScorer: pure, refit from scratch every recompute (IDF is a corpus-level
  statistic that any corpus change invalidates; see graph_service for why no
  fitted artifact is ever cached or persisted).
"""

import math
import re
import threading
from dataclasses import dataclass
from typing import Any

# Stored evidence cap per edge. A module constant, not a config knob: it bounds
# the JSON column size, does not affect the score, and nobody tunes it.
MAX_SHARED_ENTITIES = 25

_WS_RUN = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"^[\W\d_]+$")

# spaCy components en_core_web_sm runs by default; NER only needs tok2vec+ner,
# the rest (tagger/parser/attribute_ruler/lemmatizer) is dead weight here.
_DISABLED_PIPES = ["tagger", "parser", "attribute_ruler", "lemmatizer"]


def normalize_entity(text: str) -> str:
    """Casefold, collapse whitespace runs, strip a leading article. Exact-match
    normalization only — no alias or fuzzy merging ("Anthropic" vs "Anthropic
    PBC" stay distinct). Merging aliases creates false positives and is a
    research problem, not a scoring primitive; accepted limitation."""
    norm = _WS_RUN.sub(" ", text.strip().casefold())
    if norm.startswith("the "):
        norm = norm[4:]
    return norm


class EntityExtractor:
    """Lazy spaCy singleton — the exact DenseEmbedder discipline: spacy is
    imported inside the loader, double-checked threading.Lock, sync methods
    called via asyncio.to_thread by the service."""

    def __init__(self, model_name: str, keep_labels: frozenset[str], min_len: int) -> None:
        self._model_name = model_name
        self._keep_labels = keep_labels
        self._min_len = min_len
        self._nlp: Any = None
        self._lock = threading.Lock()

    def _get_nlp(self) -> Any:
        if self._nlp is None:
            with self._lock:
                if self._nlp is None:
                    import spacy

                    self._nlp = spacy.load(self._model_name, disable=_DISABLED_PIPES)
        return self._nlp

    def extract(self, texts: list[str]) -> dict[tuple[str, str], int]:
        """One document's chunk texts -> {(normalized_text, label): mention_count}.

        nlp.pipe over chunks (batch_size=32): a ~400-token chunk is spaCy's ideal
        unit and avoids max_length issues on huge concatenations. Dedup is by the
        normalized (text, label) key, so the 15% chunk overlap cannot double-
        CREATE entities; it can inflate mention counts slightly, which is
        harmless because scoring is presence-based (counts are display-only).
        """
        counts: dict[tuple[str, str], int] = {}
        if not texts:
            return counts
        for doc in self._get_nlp().pipe(texts, batch_size=32):
            for ent in doc.ents:
                if ent.label_ not in self._keep_labels:
                    continue
                norm = normalize_entity(ent.text)
                # Drop the noise NER inevitably yields: too short after
                # normalization, or purely digits/punctuation ("2024", "#1").
                if len(norm) < self._min_len or _NON_ALNUM.match(norm):
                    continue
                key = (norm, ent.label_)
                counts[key] = counts.get(key, 0) + 1
        return counts


@dataclass(frozen=True)
class SharedEntityScore:
    text: str
    label: str
    idf: float
    count_a: int
    count_b: int


@dataclass(frozen=True)
class EntityOverlap:
    score: float  # weighted Jaccard in [0, 1]
    shared: list[SharedEntityScore]  # sorted by idf desc, capped at MAX_SHARED_ENTITIES


class EntityScorer:
    """Fit once per recompute over every done document's entity map; score pairs.

    idf(e) = log(1 + N/df(e)), natural log. The `1 +` smoothing is load-bearing:
    with plain log(N/df), an entity present in BOTH docs of a 2-document corpus
    has df = N -> idf 0 -> a genuinely shared "DINOv3" would contribute NOTHING
    and the entity signal would be dead exactly when the corpus is smallest.
    Smoothed, df=N gives log 2 ~ 0.69 (still the floor) while df=1 of N=20 gives
    log 21 ~ 3.04 — rarity still dominates, tiny corpora still work.
    """

    def __init__(self, doc_entities: dict[str, dict[tuple[str, str], int]]) -> None:
        self._docs = doc_entities
        n_docs = len(doc_entities)
        df: dict[tuple[str, str], int] = {}
        for entities in doc_entities.values():
            for key in entities:
                df[key] = df.get(key, 0) + 1
        self._idf = {key: math.log(1 + n_docs / count) for key, count in df.items()}

    def idf(self, key: tuple[str, str]) -> float:
        return self._idf.get(key, 0.0)

    def score(self, doc_a: str, doc_b: str) -> EntityOverlap:
        """Weighted Jaccard: sum of shared entities' idf over sum of the union's
        idf. Chosen over cosine of TF-IDF entity vectors because (1) it has a
        true zero — no shared entities is exactly 0.0, which the combiner and
        threshold rely on — and (2) it decomposes term-by-term: each shared
        entity's numerator contribution IS its evidence weight, mapping 1:1 onto
        the UI chips and the Phase 4 LLM prompt. Cosine mixes counts and norms
        and cannot be explained entity-by-entity.

        Presence, not counts: within-document frequency is length-biased (a
        40-page doc mentions everything more) and chunk overlap inflates it;
        corpus rarity carries the discriminative signal. Counts are retained
        purely for display ("DINOv3 x7 / x3").
        """
        ents_a = self._docs.get(doc_a, {})
        ents_b = self._docs.get(doc_b, {})
        union = set(ents_a) | set(ents_b)
        if not union:
            return EntityOverlap(0.0, [])
        shared_keys = set(ents_a) & set(ents_b)
        shared_idf = sum(self._idf[k] for k in shared_keys)
        union_idf = sum(self._idf[k] for k in union)
        score = shared_idf / union_idf if union_idf > 0 else 0.0
        shared = sorted(
            (
                SharedEntityScore(
                    text=key[0],
                    label=key[1],
                    idf=round(self._idf[key], 4),
                    count_a=ents_a[key],
                    count_b=ents_b[key],
                )
                for key in shared_keys
            ),
            key=lambda s: (-s.idf, s.text),
        )
        return EntityOverlap(score, shared[:MAX_SHARED_ENTITIES])

    def top_entities(self, doc_id: str) -> list[tuple[str, str, float, int]]:
        """A document's full entity list as (text, label, idf, count), idf-desc —
        the node-attribute source (stored whole; the API truncates)."""
        entities = self._docs.get(doc_id, {})
        return sorted(
            (
                (key[0], key[1], round(self._idf[key], 4), count)
                for key, count in entities.items()
            ),
            key=lambda e: (-e[2], e[0]),
        )
