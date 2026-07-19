"""Deterministic non-LLM explanation fallback.

Pure and dependency-free: honest prose assembled from stored evidence, clearly
labelled generator='template' on the wire. Used when the LLM is disabled or
unavailable — the graceful-degrade path can never itself fail.
"""

from app.llm.prompt import EdgeEvidence


class TemplateExplainer:
    """Renders 2-3 sentences purely from structured evidence. Deliberately NOT
    an LLMClient implementation: it consumes evidence, not a prompt — degrade
    selection happens one level up, in ExplanationService."""

    model_id = "template"

    def render(self, ev: EdgeEvidence) -> str:
        sentences = [self._link_sentence(ev)]
        evidence = self._evidence_sentence(ev)
        if evidence:
            sentences.append(evidence)
        sentences.append(
            f"Signal scores: semantic {ev.semantic_score:.2f}, "
            f"entity {ev.entity_score:.2f}, topic {ev.topic_score:.2f} "
            f"(combined {ev.combined_score:.2f})."
        )
        return " ".join(sentences)

    @staticmethod
    def _link_sentence(ev: EdgeEvidence) -> str:
        return f'"{ev.doc_a}" and "{ev.doc_b}" are linked mainly by {_signal_phrase(ev)}.'

    @staticmethod
    def _evidence_sentence(ev: EdgeEvidence) -> str | None:
        if ev.shared_entities:
            top = ev.shared_entities[:3]
            names = ", ".join(e.text for e in top)
            rarest = ev.shared_entities[0]  # idf-desc: the rarest shared entity
            return (
                f"Both documents mention {names} — "
                f'"{rarest.text}" appears {rarest.count_a}× in the first '
                f"and {rarest.count_b}× in the second."
            )
        if ev.pairs:
            best = ev.pairs[0]
            if best.where_a and best.where_b:
                return (
                    f"The closest passages are {best.where_a} of the first document "
                    f"and {best.where_b} of the second "
                    f"(similarity {best.similarity:.2f})."
                )
            return f"Their closest passages overlap with similarity {best.similarity:.2f}."
        return None


def _signal_phrase(ev: EdgeEvidence) -> str:
    if ev.dominant_signal == "semantic":
        if ev.pairs:
            return (
                "closely related passages "
                f"(top pair similarity {ev.pairs[0].similarity:.2f})"
            )
        return "closely related passages"
    if ev.dominant_signal == "entity" and ev.shared_entities:
        texts = [e.text for e in ev.shared_entities]
        if len(texts) == 1:
            return f"shared references to {texts[0]}"
        if len(texts) == 2:
            return f"shared references to {texts[0]} and {texts[1]}"
        rest = len(texts) - 2
        noun = "other entity" if rest == 1 else "other entities"
        return f"shared references to {texts[0]}, {texts[1]} and {rest} {noun}"
    if ev.dominant_signal == "entity":
        return "shared named entities"
    return "overlapping topic vocabulary"
