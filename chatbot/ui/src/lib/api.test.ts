import { describe, expect, it } from "vitest";
import { describeEvent, parseSSEBlock, trimHistory } from "./api";

describe("parseSSEBlock", () => {
  it("parses a named JSON event", () => {
    expect(parseSSEBlock('event: done\ndata: {"status":"answered"}')).toEqual({
      event: "done",
      data: { status: "answered" },
    });
  });

  it("ignores blocks without data", () => {
    expect(parseSSEBlock("event: ping")).toBeNull();
  });
});


describe("trimHistory", () => {
  it("keeps only the last 12 non-empty user/assistant turns", () => {
    const turns = Array.from({ length: 20 }, (_, index) => ({
      role: index % 2 === 0 ? ("user" as const) : ("assistant" as const),
      content: `turn ${index}`,
    }));
    const trimmed = trimHistory([...turns, { role: "assistant", content: "  " }]);
    expect(trimmed).toHaveLength(12);
    expect(trimmed[0].content).toBe("turn 8");
  });
});

describe("describeEvent", () => {
  it("labels live query events", () => {
    expect(describeEvent({ event: "query_start", data: { iteration: 2, action: "paper_venue" } })).toBe(
      "Truy vấn #2: paper venue",
    );
    expect(describeEvent({ event: "done", data: {} })).toBeNull();
  });
});
