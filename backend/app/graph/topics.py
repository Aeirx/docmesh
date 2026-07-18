"""Topic overlap: NMF over chunk-level TF-IDF + Jensen-Shannon similarity.

WHY NMF and not BERTopic: BERTopic is embeddings + UMAP + HDBSCAN + c-TF-IDF —
heavy, nondeterministic, fragile on CPU-only Windows, and HDBSCAN labels most of
a 20-document corpus as outliers. NMF over TF-IDF is deterministic with nndsvda
init, its non-negative components read directly as term-weighted topics, and
every line is defensible without citing a framework.

WHY the fit runs on CHUNKS, not documents: (1) sample size — 10-20 documents
give the factorization 10-20 rows, far too few for stability; hundreds of chunks
give it a real matrix to decompose; (2) granularity — chunk-level topics capture
sub-document themes, the same thesis that has the semantic signal scoring chunk
pairs instead of doc centroids. A document's distribution is the mean of its
chunks' NMF loadings, L1-normalized into a probability distribution.

sklearn/scipy are imported inside the functions (lazy-model rule): this module
is reachable from app.main via the service, and the fast test tier must not pay
for — or require — the imports at collection time.
"""

from dataclasses import dataclass

import numpy as np

_TERMS_PER_TOPIC = 5  # component "name" length for labels/UI


@dataclass(frozen=True)
class TopicModel:
    n_components: int
    doc_distributions: dict[str, np.ndarray]  # (k,) each, L1-normalized; may be all-zero
    topic_terms: list[list[str]]  # top TF-IDF terms per component


def fit_topics(
    doc_chunks: dict[str, list[str]], *, n_topics: int, random_state: int
) -> TopicModel | None:
    """Fit TF-IDF + NMF on the chunk corpus; None when the corpus is degenerate
    (no docs, or an empty vocabulary after stop-word filtering) — the caller
    scores topic overlap as 0.0 everywhere."""
    from sklearn.decomposition import NMF
    from sklearn.feature_extraction.text import TfidfVectorizer

    texts = [t for chunks in doc_chunks.values() for t in chunks]  # stable doc order
    if not texts:
        return None
    vec = TfidfVectorizer(
        stop_words="english",
        max_features=5000,
        # min_df=2 on a tiny corpus can empty the vocabulary outright.
        min_df=2 if len(texts) >= 5 else 1,
        sublinear_tf=True,
    )
    try:
        tfidf = vec.fit_transform(texts)
    except ValueError:  # "empty vocabulary" — stop-word-only corpus
        return None

    # NMF (with nndsvda init) requires k <= min(samples, features) — the clamp is
    # a hard ceiling, never a floor: a single-chunk corpus legally fits k=1 (one
    # degenerate topic for the lone document's node attributes; no pairs exist to
    # score anyway). Shapes are >= 1 here: no texts returned None above, and an
    # empty vocabulary already raised.
    k = min(n_topics, tfidf.shape[0], tfidf.shape[1])
    # init="nndsvda" is the defensibility keystone: deterministic SVD-based
    # initialization, so the same corpus + seed always yields the same topics —
    # testable, and no "it clustered differently this run" in a demo.
    nmf = NMF(n_components=k, init="nndsvda", random_state=random_state, max_iter=400)
    loadings = nmf.fit_transform(tfidf)  # (n_chunks, k)

    distributions: dict[str, np.ndarray] = {}
    row = 0
    for doc_id, chunks in doc_chunks.items():
        block = loadings[row : row + len(chunks)]
        row += len(chunks)
        mean = block.mean(axis=0) if len(block) else np.zeros(k)
        total = float(mean.sum())
        # A zero vector (no chunk loads on any topic) is kept as-is and guarded
        # in topic_similarity — "no evidence" must never read as "similar".
        distributions[doc_id] = (mean / total) if total > 0 else mean

    feature_names = vec.get_feature_names_out()
    topic_terms = [
        [str(feature_names[idx]) for idx in np.argsort(component)[::-1][:_TERMS_PER_TOPIC]]
        for component in nmf.components_
    ]
    return TopicModel(n_components=k, doc_distributions=distributions, topic_terms=topic_terms)


def topic_similarity(p: "np.ndarray | None", q: "np.ndarray | None") -> float:
    """1 - jensenshannon(p, q, base=2).

    JS is the right comparator for probability distributions: symmetric and
    finite on disjoint supports (unlike KL). Base 2 bounds the distance in
    [0, 1], so the similarity is [0, 1] with identical distributions -> exactly
    1.0. Returns 0.0 if either side is None or all-zero: jensenshannon on a zero
    vector yields nan, which must never escape into a stored score — and "no
    evidence" is not "similar".
    """
    from scipy.spatial.distance import jensenshannon

    if p is None or q is None or float(np.sum(p)) == 0.0 or float(np.sum(q)) == 0.0:
        return 0.0
    distance = float(jensenshannon(p, q, base=2))
    if np.isnan(distance):
        # Zero vectors are already excluded above, so a nan here can only come
        # from floating-point rounding driving a ~0 divergence slightly negative
        # before scipy's sqrt — i.e. the distributions are numerically identical.
        distance = 0.0
    return min(1.0, max(0.0, 1.0 - distance))
