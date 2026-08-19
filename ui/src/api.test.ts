import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, approve, fetchAudit, fetchComparison, recordReview } from "./api";

function respondWith(status: number, body: unknown) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchComparison", () => {
  it("returns the ranked result for a comparison", async () => {
    const fetcher = respondWith(200, {
      comparison_id: 1,
      result: { ranked: [], unranked: [], status: "pending_review", revision: 0 },
    });
    vi.stubGlobal("fetch", fetcher);

    const result = await fetchComparison(1);

    expect(result.status).toBe("pending_review");
    expect(fetcher).toHaveBeenCalledWith("/api/comparisons/1", expect.anything());
  });

  it("raises the server's own message when a comparison is missing", async () => {
    vi.stubGlobal("fetch", respondWith(404, { detail: "comparison 9 not found" }));

    await expect(fetchComparison(9)).rejects.toThrow("comparison 9 not found");
  });
});

describe("recordReview", () => {
  it("sends the actor, reason and target the gate requires", async () => {
    const fetcher = respondWith(200, { comparison_id: 1, status: "pending_review" });
    vi.stubGlobal("fetch", fetcher);

    await recordReview(1, {
      actor: "lead@example.com",
      action: "flag_dismiss",
      candidate: "bob",
      target: "3f2a91c40b7e",
      reason: "employer-owned import",
    });

    const [, init] = fetcher.mock.calls[0];
    expect(JSON.parse(init.body)).toMatchObject({
      actor: "lead@example.com",
      action: "flag_dismiss",
      reason: "employer-owned import",
    });
  });

  it("surfaces a refusal rather than swallowing it", async () => {
    vi.stubGlobal(
      "fetch",
      respondWith(400, { detail: "every review action needs a reason" }),
    );

    await expect(
      recordReview(1, {
        actor: "lead",
        action: "flag_dismiss",
        candidate: "bob",
        target: "abc",
        reason: "",
      }),
    ).rejects.toThrow("every review action needs a reason");
  });

  it("carries the status code so a caller can tell a refusal from an outage", async () => {
    vi.stubGlobal("fetch", respondWith(409, { detail: "pending_review" }));

    await expect(approve(1, "lead")).rejects.toMatchObject({
      status: 409,
      name: "ApiError",
    });
  });
});

describe("ApiError", () => {
  it("falls back to a readable message when the body has no detail", async () => {
    vi.stubGlobal("fetch", respondWith(500, {}));

    await expect(fetchAudit(1)).rejects.toThrow(/500/);
  });

  it("is an Error, so it survives normal error handling", () => {
    expect(new ApiError("nope", 400)).toBeInstanceOf(Error);
  });
});

describe("a broken environment", () => {
  it("names the problem when a 200 carries something that is not JSON", async () => {
    // The dev proxy misrouting to index.html used to surface as an unrelated
    // TypeError three layers away. It should name itself here instead.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => {
          throw new SyntaxError("Unexpected token <");
        },
      }),
    );

    await expect(fetchAudit(1)).rejects.toThrow(/not JSON/);
  });
});

describe("fetchAudit", () => {
  it("returns the log in the order the server gave it", async () => {
    vi.stubGlobal(
      "fetch",
      respondWith(200, {
        comparison_id: 1,
        audit_log: [
          { actor: "lead", action: "flag_dismiss", reason: "false positive" },
          { actor: "lead", action: "approve", reason: "approved revision 0" },
        ],
      }),
    );

    const log = await fetchAudit(1);

    expect(log.map((row) => row.action)).toEqual(["flag_dismiss", "approve"]);
  });
});
