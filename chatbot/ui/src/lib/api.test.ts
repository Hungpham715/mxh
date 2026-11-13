import { describe, expect, it } from "vitest";
import { parseSSEBlock } from "./api";

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

