/** Pure answer-text segmentation. The backend guarantees the wire only carries
 *  single-number markers (`[1]`, never `[1, 2]`) and only VERIFIED ones —
 *  hallucinated markers were stripped server-side — so the client just splits
 *  and renders; no defensive validation needed here. */

export type AnswerSegment = { kind: "text"; text: string } | { kind: "cite"; marker: number };

const MARKER = /\[(\d+)\]/g;

export function splitAnswer(answer: string): AnswerSegment[] {
  const segments: AnswerSegment[] = [];
  let cursor = 0;
  for (const match of answer.matchAll(MARKER)) {
    if (match.index > cursor) {
      segments.push({ kind: "text", text: answer.slice(cursor, match.index) });
    }
    segments.push({ kind: "cite", marker: Number(match[1]) });
    cursor = match.index + match[0].length;
  }
  if (cursor < answer.length) {
    segments.push({ kind: "text", text: answer.slice(cursor) });
  }
  return segments;
}
