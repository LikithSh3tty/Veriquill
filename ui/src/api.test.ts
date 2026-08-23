import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  addCandidate,
  approve,
  createComparison,
  fetchAudit,
  fetchCandidates,
  fetchComparison,
  fetchIntakeJob,
  clearApiKey,
  readApiKey,
  recordReview,
  storeApiKey,
} from "./api";

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

describe("intake", () => {
  it("posts the handle as form data, not JSON", async () => {
    const fetcher = vi.fn().mockResolvedValue({
      ok: true,
      status: 202,
      json: async () => ({ job: { id: "j1", handle: "octocat", status: "queued" } }),
    });
    vi.stubGlobal("fetch", fetcher);

    const job = await addCandidate("octocat");

    const [, init] = fetcher.mock.calls[0];
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get("handle")).toBe("octocat");
    expect(job.status).toBe("queued");
  });

  it("does not force a content type that would break the upload boundary", async () => {
    const fetcher = vi.fn().mockResolvedValue({
      ok: true,
      status: 202,
      json: async () => ({ job: { id: "j1", handle: "octocat", status: "queued" } }),
    });
    vi.stubGlobal("fetch", fetcher);

    await addCandidate("octocat", {
      resume: new File(["cv"], "cv.pdf", { type: "application/pdf" }),
    });

    const [, init] = fetcher.mock.calls[0];
    expect(init.headers?.["Content-Type"]).toBeUndefined();
    expect((init.body as FormData).get("resume")).toBeInstanceOf(File);
  });

  it("surfaces a refused upload with the server's own words", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 400,
        json: async () => ({ detail: ".exe is not a supported format" }),
      }),
    );

    await expect(addCandidate("octocat")).rejects.toThrow(/not a supported format/);
  });

  it("reads a job's progress", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          job: { id: "j1", handle: "octocat", status: "running", error: null },
        }),
      }),
    );

    expect((await fetchIntakeJob("j1")).status).toBe("running");
  });

  it("lists the candidates that can be ranked", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          candidates: [{ handle: "alice", dossier_id: 2, stored_at: "now", flags: 1 }],
        }),
      }),
    );

    expect((await fetchCandidates()).map((c) => c.handle)).toEqual(["alice"]);
  });

  it("creates a comparison and returns its id", async () => {
    const fetcher = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ comparison_id: 4 }),
    });
    vi.stubGlobal("fetch", fetcher);

    expect(await createComparison("backend", ["alice", "bob"])).toBe(4);
    expect(JSON.parse(String(fetcher.mock.calls[0][1].body))).toMatchObject({
      rubric: "backend",
      candidates: ["alice", "bob"],
    });
  });
});

describe("the API key", () => {
  beforeEach(() => {
    clearApiKey();
  });

  it("is not sent when this browser holds none", async () => {
    const fetchMock = respondWith(200, { candidates: [] });
    vi.stubGlobal("fetch", fetchMock);

    await fetchCandidates();

    const headers = fetchMock.mock.calls[0][1].headers as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
  });

  it("is sent as a bearer token once stored", async () => {
    storeApiKey("sk_stored_key");
    const fetchMock = respondWith(200, { candidates: [] });
    vi.stubGlobal("fetch", fetchMock);

    await fetchCandidates();

    const headers = fetchMock.mock.calls[0][1].headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer sk_stored_key");
  });

  it("marks a 401 so the screen can ask for a key rather than just reporting it", async () => {
    vi.stubGlobal(
      "fetch",
      respondWith(401, { detail: "this server requires an API key" }),
    );

    await expect(fetchCandidates()).rejects.toMatchObject({
      status: 401,
      isUnauthorized: true,
    });
  });

  it("trims what was typed, since a pasted key often carries whitespace", () => {
    storeApiKey("  sk_padded  ");

    expect(readApiKey()).toBe("sk_padded");
  });
});
