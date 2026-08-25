/**
 * The review screen against a payload the API actually produced.
 *
 * Every other test in this suite hands the components objects written by hand,
 * which proves the screen works on the shape its author had in mind. It cannot
 * catch the shape drifting: a renamed field passes the Python suite, passes
 * this suite, and empties a panel on the one screen where a defect costs a
 * hiring decision.
 *
 * `contract.json` is written by tests/test_ui_contract.py from the running API,
 * and that test fails when the committed copy goes stale. So these assertions
 * are about live output, not about a fixture someone remembered to update.
 */

import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import contract from "./test/contract.json";
import { App } from "./App";
import { clearApiKey } from "./api";

type Contract = typeof contract;

function respondingWith(payload: Contract) {
  return vi.fn(async (url: string) => {
    const body = (() => {
      if (url.includes("/audit")) return { audit_log: payload.audit };
      if (url.includes("/dossiers")) return { dossiers: {} };
      if (url.includes("/candidates")) return { candidates: payload.candidates };
      if (url.includes("/rubrics")) return { rubrics: [{ name: "backend" }] };
      return { result: payload.comparison };
    })();

    return { ok: true, status: 200, json: async () => body };
  });
}

describe("the review screen against real API output", () => {
  beforeEach(() => {
    clearApiKey();
    vi.stubGlobal("fetch", respondingWith(contract));
  });

  it("renders a comparison the API produced", async () => {
    render(<App comparisonId={1} />);

    await waitFor(() => {
      expect(screen.getAllByText(/alpha/i).length).toBeGreaterThan(0);
    });
  });

  it("reads the gate state out of the payload rather than defaulting to it", async () => {
    render(<App comparisonId={1} />);

    // The fixture is an approved comparison, so the screen must say so. A
    // status field the screen cannot parse would silently read as pending.
    await waitFor(() => {
      expect(screen.getAllByText(/approved/i).length).toBeGreaterThan(0);
    });
    expect(contract.comparison.status).toBe("reviewed");
  });

  it("shows no error banner for a payload the API considers valid", async () => {
    render(<App comparisonId={1} />);

    await waitFor(() => {
      expect(screen.getAllByText(/alpha/i).length).toBeGreaterThan(0);
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("carries every dimension the ranker scored", () => {
    const dimensions = contract.comparison.ranked[0].score.dimensions.map(
      (entry) => entry.dimension,
    );

    // The six the rubric weights. A dimension dropped from the payload would
    // leave a blank row rather than an error.
    expect(dimensions).toEqual(
      expect.arrayContaining([
        "authenticity",
        "code_quality",
        "claim_corroboration",
        "test_quality",
        "security",
        "breadth",
      ]),
    );
  });

  it("carries a band with two ends, which is what the axis draws", () => {
    const { band, coverage, confidence } = contract.comparison.ranked[0].score;

    expect(band).toHaveLength(2);
    expect(typeof coverage).toBe("number");
    expect(["high", "moderate", "low"]).toContain(confidence);
  });

  it("carries the audit fields the log renders", () => {
    const [entry] = contract.audit;

    expect(entry).toMatchObject({
      actor: expect.any(String),
      action: expect.any(String),
      reason: expect.any(String),
      revision: expect.any(Number),
    });
  });
});
