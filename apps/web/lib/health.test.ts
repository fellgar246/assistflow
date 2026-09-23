import { describe, expect, it } from "vitest";
import { parseHealthStatus } from "./health";

describe("health schema", () => {
  it("accepts a healthy payload", () => {
    expect(parseHealthStatus({ status: "healthy" })).toEqual({ status: "healthy" });
  });

  it("rejects an unknown status", () => {
    expect(() => parseHealthStatus({ status: "down" })).toThrow();
  });
});
