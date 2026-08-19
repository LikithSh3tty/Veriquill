import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { JobDescription } from "./JobDescription";

const derived = {
  rubric: {
    name: "secure-backend",
    version: 1,
    weights: {
      authenticity: 0.25,
      code_quality: 0.17,
      claim_corroboration: 0.16,
      test_quality: 0.22,
      security: 0.16,
      breadth: 0.04,
    },
    minimum_bars: {},
  },
  derivation: {
    emphases: { security: ["owasp", "secure coding"], test_quality: ["unit tests"] },
    note: "Weights were raised for security, test_quality because the description asks for them.",
  },
};

function setup(overrides: Partial<Parameters<typeof JobDescription>[0]> = {}) {
  const onDerive = vi.fn().mockResolvedValue(derived);
  const onDerived = vi.fn();
  render(<JobDescription onDerive={onDerive} onDerived={onDerived} {...overrides} />);
  return { onDerive, onDerived };
}

describe("JobDescription", () => {
  it("will not derive a rubric from nothing", async () => {
    const user = userEvent.setup();
    const { onDerive } = setup();

    await user.click(screen.getByRole("button", { name: /derive/i }));

    expect(onDerive).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(/paste the job description/i);
  });

  it("sends the description and a name for it", async () => {
    const user = userEvent.setup();
    const { onDerive } = setup();

    await user.type(screen.getByLabelText(/name/i), "secure-backend");
    await user.type(screen.getByLabelText(/job description/i), "OWASP and unit tests.");
    await user.click(screen.getByRole("button", { name: /derive/i }));

    await waitFor(() =>
      expect(onDerive).toHaveBeenCalledWith("secure-backend", "OWASP and unit tests."),
    );
  });

  it("shows the weights it derived", async () => {
    const user = userEvent.setup();
    setup();

    await user.type(screen.getByLabelText(/name/i), "secure-backend");
    await user.type(screen.getByLabelText(/job description/i), "OWASP");
    await user.click(screen.getByRole("button", { name: /derive/i }));

    expect(await screen.findByText(/test quality/i)).toBeInTheDocument();
    expect(screen.getByText("22%")).toBeInTheDocument();
  });

  it("shows which phrases raised each dimension, not just the numbers", async () => {
    const user = userEvent.setup();
    setup();

    await user.type(screen.getByLabelText(/name/i), "secure-backend");
    await user.type(screen.getByLabelText(/job description/i), "OWASP");
    await user.click(screen.getByRole("button", { name: /derive/i }));

    // Two dimensions were raised, so scope to the security row specifically.
    const security = await screen.findByText(/owasp/i, { selector: ".jd__phrases" });
    expect(security).toHaveTextContent(/secure coding/i);
    expect(screen.getByText(/unit tests/i, { selector: ".jd__phrases" })).toBeInTheDocument();
  });

  it("hands the stored rubric back so a cohort can be ranked against it", async () => {
    const user = userEvent.setup();
    const { onDerived } = setup();

    await user.type(screen.getByLabelText(/name/i), "secure-backend");
    await user.type(screen.getByLabelText(/job description/i), "OWASP");
    await user.click(screen.getByRole("button", { name: /derive/i }));

    await waitFor(() => expect(onDerived).toHaveBeenCalledWith("secure-backend"));
  });

  it("surfaces a refusal from the server", async () => {
    const user = userEvent.setup();
    setup({ onDerive: vi.fn().mockRejectedValue(new Error("the job description is empty")) });

    await user.type(screen.getByLabelText(/name/i), "x");
    await user.type(screen.getByLabelText(/job description/i), "text");
    await user.click(screen.getByRole("button", { name: /derive/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/empty/i);
  });

  it("says plainly when the description named nothing", async () => {
    const user = userEvent.setup();
    setup({
      onDerive: vi.fn().mockResolvedValue({
        ...derived,
        derivation: { emphases: {}, note: "No phrase in this description named a dimension." },
      }),
    });

    await user.type(screen.getByLabelText(/name/i), "x");
    await user.type(screen.getByLabelText(/job description/i), "We are hiring.");
    await user.click(screen.getByRole("button", { name: /derive/i }));

    expect(await screen.findByText(/named a dimension/i)).toBeInTheDocument();
  });
});
