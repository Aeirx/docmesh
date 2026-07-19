/** Smoke tests for the pure graph helpers + the explanation API client.
 *  (UI rendering is exercised by the app itself; these pin the contracts.) */

import { afterEach, describe, expect, it, vi } from "vitest";

import { getEdgeExplanation } from "../../lib/api";
import { middleEllipsis } from "../../lib/format";
import {
  edgeStrokeWidth,
  nodeRadius,
  SIGNAL_COLORS,
  signalContributions,
  sizeTier,
  TOPIC_MUTED,
  TOPIC_PALETTE,
  topicColor,
} from "./colors";
import { corpusKey, loadPositions, savePositions, seedPosition } from "./layout/positions";
import { canonicalPair } from "./types";

describe("topicColor", () => {
  it("assigns distinct colors to adjacent topic ids and wraps modulo 8", () => {
    expect(topicColor(0)).not.toBe(topicColor(1));
    expect(topicColor(0)).toBe(TOPIC_PALETTE[0]);
    expect(topicColor(8)).toBe(topicColor(0));
    expect(topicColor(9)).toBe(topicColor(1));
  });

  it("maps null/undefined to the muted neutral", () => {
    expect(topicColor(null)).toBe(TOPIC_MUTED);
    expect(topicColor(undefined)).toBe(TOPIC_MUTED);
  });
});

describe("signal mapping", () => {
  it("keeps the designer's three signal hexes", () => {
    expect(SIGNAL_COLORS.semantic).toBe("#a48fff");
    expect(SIGNAL_COLORS.entity).toBe("#3dc9de");
    expect(SIGNAL_COLORS.topic).toBe("#e8a33d");
  });

  it("weights contributions so the argmax matches dominant_signal semantics", () => {
    const contributions = signalContributions(
      { semantic_score: 0.9, entity_score: 0.5, topic_score: 0.1 },
      { semantic: 0.5, entity: 0.3, topic: 0.2 },
    );
    expect(contributions.map((c) => c.signal)).toEqual(["semantic", "entity", "topic"]);
    expect(contributions[0].value).toBeCloseTo(0.45);
    expect(contributions[1].value).toBeCloseTo(0.15);
    expect(contributions[2].value).toBeCloseTo(0.02);
  });
});

describe("size scale", () => {
  it("tiers by document bytes at the designer's boundaries", () => {
    expect(sizeTier(0)).toBe("s");
    expect(sizeTier(49_999)).toBe("s");
    expect(sizeTier(50_000)).toBe("m");
    expect(sizeTier(249_999)).toBe("m");
    expect(sizeTier(250_000)).toBe("l");
    expect(sizeTier(999_999)).toBe("l");
    expect(sizeTier(1_000_000)).toBe("xl");
  });

  it("derives a monotonic collision radius", () => {
    expect(nodeRadius(10_000)).toBeLessThan(nodeRadius(2_000_000));
  });

  it("maps combined score to the 1..5px stroke range", () => {
    expect(edgeStrokeWidth(0)).toBe(1);
    expect(edgeStrokeWidth(1)).toBe(5);
  });
});

describe("canonicalPair", () => {
  it("is order-insensitive", () => {
    expect(canonicalPair("b", "a")).toEqual(["a", "b"]);
    expect(canonicalPair("a", "b")).toEqual(["a", "b"]);
  });
});

describe("middleEllipsis", () => {
  it("keeps short names intact and preserves the extension end", () => {
    expect(middleEllipsis("short.pdf", 26)).toBe("short.pdf");
    const long = middleEllipsis("competitor-research-2026-h1-deep-dive.pdf", 26);
    expect(long.length).toBeLessThanOrEqual(26);
    expect(long).toContain("…");
    expect(long.endsWith("-dive.pdf")).toBe(true);
  });
});

describe("positions", () => {
  it("corpusKey is order-insensitive and id-sensitive", () => {
    expect(corpusKey(["a", "b", "c"])).toBe(corpusKey(["c", "a", "b"]));
    expect(corpusKey(["a", "b"])).not.toBe(corpusKey(["a", "b", "c"]));
  });

  it("seedPosition is deterministic and spreads nodes", () => {
    expect(seedPosition(0, 6)).toEqual(seedPosition(0, 6));
    const a = seedPosition(0, 6);
    const b = seedPosition(3, 6);
    expect(Math.hypot(a.x - b.x, a.y - b.y)).toBeGreaterThan(100);
  });

  it("round-trips through sessionStorage", () => {
    const store = new Map<string, string>();
    vi.stubGlobal("sessionStorage", {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
    });
    try {
      const key = corpusKey(["a", "b"]);
      savePositions(key, { a: { x: 1, y: 2 }, b: { x: -3, y: 4 } });
      expect(loadPositions(key)).toEqual({ a: { x: 1, y: 2 }, b: { x: -3, y: 4 } });
      expect(loadPositions("missing")).toBeNull();
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe("getEdgeExplanation", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("builds the plain and refresh URLs", async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(new Response(JSON.stringify({ explanation: "x" }), { status: 200 })),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getEdgeExplanation("doc-a", "doc-b");
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/graph/edges/doc-a/doc-b/explanation",
      undefined,
    );

    await getEdgeExplanation("doc-a", "doc-b", { refresh: true });
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/graph/edges/doc-a/doc-b/explanation?refresh=true",
      undefined,
    );
  });
});
