import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { StoredCandidate } from "../api";
import { CohortPicker } from "./CohortPicker";

const CANDIDATES: StoredCandidate[] = [
  { handle: "alice", dossier_id: 1, stored_at: "2026-08-19T10:00:00", flags: 0 },
  { handle: "bob", dossier_id: 2, stored_at: "2026-08-19T11:00:00", flags: 2 },
  { handle: "carol", dossier_id: 3, stored_at: "2026-08-19T12:00:00", flags: 1 },
];

function setup(overrides: Partial<Parameters<typeof CohortPicker>[0]> = {}) {
  const onRank = vi.fn().mockResolvedValue(7);
  const onRanked = vi.fn();
  render(
    <CohortPicker
      candidates={CANDIDATES}
      rubrics={[{ name: "backend-hire" }, { name: "frontend-hire" }]}
      onRank={onRank}
      onRanked={onRanked}
      {...overrides}
    />,
  );
  return { onRank, onRanked };
}

describe("CohortPicker", () => {
  it("lists every stored candidate", () => {
    setup();

    for (const handle of ["alice", "bob", "carol"]) {
      expect(screen.getByLabelText(new RegExp(handle))).toBeInTheDocument();
    }
  });

  it("shows how many flags each candidate carries", () => {
    setup();

    expect(screen.getByLabelText(/bob/)).toBeInTheDocument();
    expect(screen.getByText(/2 flags/)).toBeInTheDocument();
  });

  it("will not rank nobody", async () => {
    const user = userEvent.setup();
    const { onRank } = setup();

    await user.click(screen.getByRole("button", { name: /rank/i }));

    expect(onRank).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(/select at least one/i);
  });

  it("ranks the candidates that were selected", async () => {
    const user = userEvent.setup();
    const { onRank } = setup();

    await user.click(screen.getByLabelText(/alice/));
    await user.click(screen.getByLabelText(/carol/));
    await user.click(screen.getByRole("button", { name: /rank/i }));

    await waitFor(() =>
      expect(onRank).toHaveBeenCalledWith("backend-hire", ["alice", "carol"]),
    );
  });

  it("uses the rubric the reviewer chose", async () => {
    const user = userEvent.setup();
    const { onRank } = setup();

    await user.selectOptions(screen.getByLabelText(/rubric/i), "frontend-hire");
    await user.click(screen.getByLabelText(/bob/));
    await user.click(screen.getByRole("button", { name: /rank/i }));

    await waitFor(() =>
      expect(onRank).toHaveBeenCalledWith("frontend-hire", ["bob"]),
    );
  });

  it("hands back the comparison it created", async () => {
    const user = userEvent.setup();
    const { onRanked } = setup();

    await user.click(screen.getByLabelText(/alice/));
    await user.click(screen.getByRole("button", { name: /rank/i }));

    await waitFor(() => expect(onRanked).toHaveBeenCalledWith(7));
  });

  it("surfaces a refusal from the server", async () => {
    const user = userEvent.setup();
    setup({ onRank: vi.fn().mockRejectedValue(new Error("no rubric named 'ghost'")) });

    await user.click(screen.getByLabelText(/alice/));
    await user.click(screen.getByRole("button", { name: /rank/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/no rubric named/i);
  });

  it("says what to do first when no candidate has been added", () => {
    setup({ candidates: [] });

    expect(screen.getByText(/add a candidate/i)).toBeInTheDocument();
  });

  it("says what to do first when no rubric has been stored", () => {
    setup({ rubrics: [] });

    expect(screen.getByText(/rubric-add/i)).toBeInTheDocument();
  });
});
