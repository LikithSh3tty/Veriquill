import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

const ranked = (handle: string, score: number, rank: number) => ({
  handle,
  rank,
  tie_group: rank,
  drivers: [],
  score: {
    handle,
    score,
    band: [score - 0.05, score + 0.05],
    width: 0.05,
    confidence: "high",
    coverage: 1,
    dimensions: [],
    unmeasured: [],
    bar_breaches: [],
  },
});

const flagFor = (handle: string) => ({
  flag_id: `${handle}-flag`,
  check_id: "provenance.bulk_dump",
  severity: "critical",
  title: `${handle} landed one commit`,
  rationale: "because",
  confidence: 0.8,
  evidence: [{ repo: `${handle}/api`, detail: "commit a1b2" }],
});

function stubApi(overrides: Record<string, unknown> = {}) {
  const fetcher = vi.fn(async (url: string) => {
    const body =
      url.endsWith("/audit")
        ? { audit_log: [] }
        : url.endsWith("/dossiers")
          ? {
              dossiers: {
                alice: { handle: "alice", red_flag_register: [flagFor("alice")] },
                bob: { handle: "bob", red_flag_register: [flagFor("bob")] },
              },
            }
          : {
              result: {
                ranked: [ranked("alice", 0.9, 1), ranked("bob", 0.5, 2)],
                unranked: [],
                status: "pending_review",
                revision: 0,
                disclaimer: "Advisory only.",
                ...overrides,
              },
            };
    return { ok: true, status: 200, json: async () => body };
  });
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}

afterEach(() => vi.unstubAllGlobals());

describe("App", () => {
  it("shows the gate state and what it blocks", async () => {
    stubApi();
    render(<App comparisonId={1} />);

    expect(await screen.findByText(/pending review/i)).toBeInTheDocument();
    expect(screen.getByText(/nothing can be exported/i)).toBeInTheDocument();
  });

  it("selects a candidate and shows the flags belonging to them", async () => {
    stubApi();
    render(<App comparisonId={1} />);

    expect(await screen.findByText(/alice landed one commit/i)).toBeInTheDocument();
  });

  it("swaps to the newly selected candidate's own flags", async () => {
    const user = userEvent.setup();
    stubApi();
    render(<App comparisonId={1} />);

    await screen.findByText(/alice landed one commit/i);
    await user.click(screen.getByRole("button", { name: /bob/i }));

    expect(await screen.findByText(/bob landed one commit/i)).toBeInTheDocument();
    expect(screen.queryByText(/alice landed one commit/i)).not.toBeInTheDocument();
  });

  it("can act on the newly selected candidate without reselecting their flag", async () => {
    const user = userEvent.setup();
    const fetcher = stubApi();
    render(<App comparisonId={1} />);

    await screen.findByText(/alice landed one commit/i);
    await user.click(screen.getByRole("button", { name: /bob/i }));
    await screen.findByText(/bob landed one commit/i);

    await user.type(screen.getByLabelText(/reviewer/i), "lead@example.com");
    await user.type(screen.getByLabelText(/reason/i), "employer-owned import");
    await user.click(screen.getByRole("button", { name: /dismiss flag/i }));

    await waitFor(() => {
      const posted = fetcher.mock.calls.find(
        ([, init]) => init?.method === "POST" && String(init.body).includes("flag_dismiss"),
      );
      expect(posted).toBeTruthy();
      expect(JSON.parse(String(posted![1].body))).toMatchObject({
        candidate: "bob",
        target: "bob-flag",
        reason: "employer-owned import",
      });
    });
  });

  it("does not carry a reason typed for one candidate over to another", async () => {
    const user = userEvent.setup();
    stubApi();
    render(<App comparisonId={1} />);

    await screen.findByText(/alice landed one commit/i);
    await user.type(screen.getByLabelText(/reason/i), "notes about alice");
    await user.click(screen.getByRole("button", { name: /bob/i }));

    await screen.findByText(/bob landed one commit/i);
    expect(screen.getByLabelText(/reason/i)).toHaveValue("");
  });

  it("refuses to approve without a named reviewer", async () => {
    const user = userEvent.setup();
    stubApi();
    render(<App comparisonId={1} />);

    await screen.findByText(/pending review/i);
    await user.click(screen.getByRole("button", { name: /approve revision/i }));

    expect(await screen.findByText(/enter who you are/i)).toBeInTheDocument();
  });

  it("reports an unreachable API instead of rendering an empty page", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        json: async () => ({ detail: "comparison 7 not found" }),
      }),
    );
    render(<App comparisonId={7} />);

    expect(await screen.findByText(/comparison 7 not found/i)).toBeInTheDocument();
  });
});
