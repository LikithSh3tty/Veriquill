import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { RankedRow } from "../api";
import { ReviewPanel } from "./ReviewPanel";

const flag = {
  flag_id: "3f2a91c40b7e",
  check_id: "provenance.bulk_dump",
  severity: "critical",
  title: "Whole codebase landed in one commit",
  rationale: "94% of inserted lines arrived in the first commit",
  confidence: 0.8,
  evidence: [{ repo: "bob/payments", detail: "commit a1b2c3d, 12k lines" }],
};

const row: RankedRow = {
  handle: "bob",
  rank: 2,
  tie_group: 1,
  drivers: ["authenticity -0.30 against the cohort median"],
  human_band: null,
  override_reason: null,
  score: {
    handle: "bob",
    score: 0.54,
    band: [0.49, 0.59],
    width: 0.05,
    confidence: "high",
    coverage: 0.9,
    dimensions: [],
    unmeasured: [],
    bar_breaches: [],
  },
};

function setup(overrides: Partial<Parameters<typeof ReviewPanel>[0]> = {}) {
  const onAction = vi.fn().mockResolvedValue(undefined);
  render(
    <ReviewPanel
      row={row}
      flags={[flag]}
      actor="lead@example.com"
      onAction={onAction}
      {...overrides}
    />,
  );
  return { onAction };
}

describe("ReviewPanel", () => {
  it("lists each flag with the evidence behind it", () => {
    setup();

    expect(screen.getByText(/whole codebase landed in one commit/i)).toBeInTheDocument();
    expect(screen.getByText(/commit a1b2c3d/i)).toBeInTheDocument();
  });

  it("refuses to dismiss a flag without a reason", async () => {
    const user = userEvent.setup();
    const { onAction } = setup();

    await user.click(screen.getByRole("button", { name: /dismiss/i }));

    expect(onAction).not.toHaveBeenCalled();
    expect(screen.getByText(/give a reason/i)).toBeInTheDocument();
  });

  it("treats whitespace as no reason at all", async () => {
    const user = userEvent.setup();
    const { onAction } = setup();

    await user.type(screen.getByLabelText(/reason/i), "   ");
    await user.click(screen.getByRole("button", { name: /dismiss/i }));

    expect(onAction).not.toHaveBeenCalled();
  });

  it("sends the dismissal with its reason once one is given", async () => {
    const user = userEvent.setup();
    const { onAction } = setup();

    await user.type(screen.getByLabelText(/reason/i), "employer-owned import");
    await user.click(screen.getByRole("button", { name: /dismiss/i }));

    expect(onAction).toHaveBeenCalledWith({
      actor: "lead@example.com",
      action: "flag_dismiss",
      candidate: "bob",
      target: "3f2a91c40b7e",
      reason: "employer-owned import",
    });
  });

  it("confirms a flag through the same reason requirement", async () => {
    const user = userEvent.setup();
    const { onAction } = setup();

    await user.type(screen.getByLabelText(/reason/i), "checked the history, it holds");
    await user.click(screen.getByRole("button", { name: /confirm/i }));

    expect(onAction).toHaveBeenCalledWith(
      expect.objectContaining({ action: "flag_confirm" }),
    );
  });

  it("requires an actor before anything can be recorded", async () => {
    const user = userEvent.setup();
    const { onAction } = setup({ actor: "" });

    await user.type(screen.getByLabelText(/reason/i), "a real reason");
    await user.click(screen.getByRole("button", { name: /dismiss/i }));

    expect(onAction).not.toHaveBeenCalled();
    expect(screen.getByText(/who you are/i)).toBeInTheDocument();
  });

  it("shows the server's refusal when the gate rejects an action", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn().mockRejectedValue(new Error("bob has no flag 'zzz'"));
    render(
      <ReviewPanel row={row} flags={[flag]} actor="lead" onAction={onAction} />,
    );

    await user.type(screen.getByLabelText(/reason/i), "stale id");
    await user.click(screen.getByRole("button", { name: /dismiss/i }));

    expect(await screen.findByText(/bob has no flag/i)).toBeInTheDocument();
  });

  it("shows a human band override next to what the machine said", () => {
    render(
      <ReviewPanel
        row={{ ...row, human_band: "strong hire", override_reason: "reference call" }}
        flags={[flag]}
        actor="lead"
        onAction={vi.fn()}
      />,
    );

    expect(screen.getByText(/strong hire/i)).toBeInTheDocument();
    expect(screen.getByText(/reference call/i)).toBeInTheDocument();
    expect(screen.getByText(/0\.54/)).toBeInTheDocument();
  });

  it("says so plainly when a candidate has no flags", () => {
    render(<ReviewPanel row={row} flags={[]} actor="lead" onAction={vi.fn()} />);

    expect(screen.getByText(/no flags were raised/i)).toBeInTheDocument();
  });
});
