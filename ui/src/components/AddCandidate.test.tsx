import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { IntakeJob } from "../api";
import { AddCandidate } from "./AddCandidate";

const queued: IntakeJob = {
  id: "j1",
  handle: "octocat",
  status: "queued",
  error: null,
  dossier_id: null,
  created_at: "2026-08-19T10:00:00",
  finished_at: null,
};

function setup(overrides: Partial<Parameters<typeof AddCandidate>[0]> = {}) {
  const onSubmit = vi.fn().mockResolvedValue(queued);
  const onPoll = vi.fn().mockResolvedValue({ ...queued, status: "done", dossier_id: 3 });
  const onAdded = vi.fn();
  render(
    <AddCandidate
      onSubmit={onSubmit}
      onPoll={onPoll}
      onAdded={onAdded}
      pollMs={5}
      {...overrides}
    />,
  );
  return { onSubmit, onPoll, onAdded };
}

describe("AddCandidate", () => {
  it("says how long this takes before anyone starts waiting", () => {
    setup();

    expect(screen.getByText(/minute/i)).toBeInTheDocument();
  });

  it("will not submit an empty handle", async () => {
    const user = userEvent.setup();
    const { onSubmit } = setup();

    await user.click(screen.getByRole("button", { name: /add candidate/i }));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText(/enter a github username/i)).toBeInTheDocument();
  });

  it("submits the handle it was given", async () => {
    const user = userEvent.setup();
    const { onSubmit } = setup();

    await user.type(screen.getByLabelText(/github username/i), "octocat");
    await user.click(screen.getByRole("button", { name: /add candidate/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith("octocat", {}));
  });

  it("reports progress rather than leaving a dead button", async () => {
    const user = userEvent.setup();
    setup();

    await user.type(screen.getByLabelText(/github username/i), "octocat");
    await user.click(screen.getByRole("button", { name: /add candidate/i }));

    expect(await screen.findByRole("status")).toHaveTextContent(/octocat/i);
  });

  it("tells the caller once the candidate is stored", async () => {
    const user = userEvent.setup();
    const { onAdded } = setup();

    await user.type(screen.getByLabelText(/github username/i), "octocat");
    await user.click(screen.getByRole("button", { name: /add candidate/i }));

    await waitFor(() => expect(onAdded).toHaveBeenCalledWith("octocat"));
  });

  it("shows why an analysis failed, in the server's words", async () => {
    const user = userEvent.setup();
    setup({
      onPoll: vi
        .fn()
        .mockResolvedValue({ ...queued, status: "failed", error: "GitHub said 404 for 'ghost'" }),
    });

    await user.type(screen.getByLabelText(/github username/i), "ghost");
    await user.click(screen.getByRole("button", { name: /add candidate/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/404/);
  });

  it("shows a refusal from the submit itself", async () => {
    const user = userEvent.setup();
    setup({ onSubmit: vi.fn().mockRejectedValue(new Error("not a GitHub username")) });

    await user.type(screen.getByLabelText(/github username/i), "bad name");
    await user.click(screen.getByRole("button", { name: /add candidate/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/not a GitHub username/i);
  });

  it("passes uploaded documents along", async () => {
    const user = userEvent.setup();
    const { onSubmit } = setup();

    await user.type(screen.getByLabelText(/github username/i), "octocat");
    await user.upload(
      screen.getByLabelText(/résumé|resume/i),
      new File(["cv"], "cv.pdf", { type: "application/pdf" }),
    );
    await user.click(screen.getByRole("button", { name: /add candidate/i }));

    await waitFor(() => {
      const [, files] = onSubmit.mock.calls[0];
      expect(files.resume?.name).toBe("cv.pdf");
    });
  });

  it("says what happens to an uploaded document", () => {
    setup();

    expect(screen.getByText(/removed|not kept|deleted/i)).toBeInTheDocument();
  });
});
