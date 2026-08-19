import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { RankedRow } from "../api";
import { BandAxis } from "./BandAxis";

function row(handle: string, score: number, width: number, rank: number, tie = 0): RankedRow {
  return {
    handle,
    rank,
    tie_group: tie,
    drivers: [`authenticity +0.10 against the cohort median`],
    score: {
      handle,
      score,
      band: [Math.max(0, score - width), Math.min(1, score + width)],
      width,
      confidence: width < 0.1 ? "high" : "low",
      coverage: 1 - width,
      dimensions: [],
      unmeasured: [],
      bar_breaches: [],
    },
  };
}

describe("BandAxis", () => {
  it("lists every candidate with its rank", () => {
    render(<BandAxis rows={[row("alice", 0.9, 0.05, 1), row("bob", 0.5, 0.05, 2)]} />);

    expect(screen.getByText("alice")).toBeInTheDocument();
    expect(screen.getByText("bob")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("marks a narrow gap without collapsing the order", () => {
    const alice = row("alice", 0.9, 0.2, 1, 0);
    const bob = { ...row("bob", 0.88, 0.2, 2, 0), separated_weakly: true };

    render(<BandAxis rows={[alice, bob]} />);

    // The order still reads 1, 2 — the caveat rides on the row that earned it.
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText(/narrow gap/i)).toBeInTheDocument();
  });

  it("says nothing about a gap the evidence carries comfortably", () => {
    render(<BandAxis rows={[row("alice", 0.9, 0.02, 1, 0), row("bob", 0.2, 0.02, 2, 1)]} />);

    expect(screen.queryByText(/narrow gap/i)).not.toBeInTheDocument();
  });

  it("does not call two separable candidates tied", () => {
    render(<BandAxis rows={[row("alice", 0.9, 0.02, 1, 0), row("bob", 0.2, 0.02, 2, 1)]} />);

    expect(screen.queryByText(/tied/i)).not.toBeInTheDocument();
  });

  it("states the interval in text, not only as a drawn bar", () => {
    render(<BandAxis rows={[row("alice", 0.9, 0.05, 1)]} />);

    expect(screen.getByText(/0\.85\s*–\s*0\.95/)).toBeInTheDocument();
  });

  it("reports coverage next to the score so a wide band is explained", () => {
    render(<BandAxis rows={[row("alice", 0.6, 0.3, 1)]} />);

    const entry = screen.getByRole("listitem");
    expect(within(entry).getByText(/coverage/i)).toBeInTheDocument();
  });

  it("gives each band an accessible description of its range", () => {
    render(<BandAxis rows={[row("alice", 0.9, 0.05, 1)]} />);

    const meter = screen.getByRole("meter", { name: /alice/i });
    expect(meter).toHaveAttribute("aria-valuemin", "0.85");
    expect(meter).toHaveAttribute("aria-valuemax", "0.95");
    expect(meter).toHaveAttribute("aria-valuenow", "0.9");
  });

  it("selects a candidate when their row is activated", async () => {
    const seen: string[] = [];
    render(
      <BandAxis rows={[row("alice", 0.9, 0.05, 1)]} onSelect={(handle) => seen.push(handle)} />,
    );

    screen.getByRole("button", { name: /alice/i }).click();

    expect(seen).toEqual(["alice"]);
  });

  it("shows an empty state rather than a bare axis when nobody is ranked", () => {
    render(<BandAxis rows={[]} />);

    expect(screen.getByText(/no candidate has been ranked/i)).toBeInTheDocument();
  });
});
