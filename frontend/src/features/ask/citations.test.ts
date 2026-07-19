import { describe, expect, it } from "vitest";

import { splitAnswer } from "./citations";

describe("splitAnswer", () => {
  it("splits text and citation markers in order", () => {
    expect(splitAnswer("As shown [1] and [2].")).toEqual([
      { kind: "text", text: "As shown " },
      { kind: "cite", marker: 1 },
      { kind: "text", text: " and " },
      { kind: "cite", marker: 2 },
      { kind: "text", text: "." },
    ]);
  });

  it("returns a single text segment when there are no markers", () => {
    expect(splitAnswer("No citations here.")).toEqual([
      { kind: "text", text: "No citations here." },
    ]);
  });

  it("handles leading and adjacent markers", () => {
    expect(splitAnswer("[1][2] agree.")).toEqual([
      { kind: "cite", marker: 1 },
      { kind: "cite", marker: 2 },
      { kind: "text", text: " agree." },
    ]);
  });

  it("returns nothing for an empty answer", () => {
    expect(splitAnswer("")).toEqual([]);
  });
});
