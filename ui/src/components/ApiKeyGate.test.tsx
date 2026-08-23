/**
 * Asking for a key only when the server has asked for one.
 *
 * A server with no keys configured never refuses, and a reviewer there must
 * never be prompted for a credential that does not exist. That is the case
 * these tests care about most, because getting it wrong makes the open
 * deployment look broken.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiKeyGate } from "./ApiKeyGate";
import { clearApiKey, readApiKey } from "../api";

describe("ApiKeyGate", () => {
  beforeEach(() => {
    clearApiKey();
  });

  it("shows nothing on a server that never refused", () => {
    const { container } = render(
      <ApiKeyGate refused={false} hasKey={false} onSaved={vi.fn()} />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("asks for a key once a request was refused", () => {
    render(<ApiKeyGate refused hasKey={false} onSaved={vi.fn()} />);

    expect(screen.getByTestId("key-gate")).toBeInTheDocument();
    expect(screen.getByLabelText(/needs an API key/i)).toBeInTheDocument();
  });

  it("says the key was wrong rather than missing when one is already held", () => {
    render(<ApiKeyGate refused hasKey onSaved={vi.fn()} />);

    expect(screen.getByLabelText(/was refused/i)).toBeInTheDocument();
  });

  it("stores what was typed and tells the screen to retry", async () => {
    const onSaved = vi.fn();
    render(<ApiKeyGate refused hasKey={false} onSaved={onSaved} />);

    await userEvent.type(screen.getByLabelText(/needs an API key/i), "sk_typed_key");
    await userEvent.click(screen.getByRole("button", { name: /use this key/i }));

    expect(readApiKey()).toBe("sk_typed_key");
    expect(onSaved).toHaveBeenCalled();
  });

  it("will not submit an empty key", async () => {
    const onSaved = vi.fn();
    render(<ApiKeyGate refused hasKey={false} onSaved={onSaved} />);

    expect(screen.getByRole("button", { name: /use this key/i })).toBeDisabled();
    expect(onSaved).not.toHaveBeenCalled();
  });

  it("never renders the stored key back onto the screen", () => {
    render(<ApiKeyGate refused={false} hasKey onSaved={vi.fn()} />);

    expect(screen.queryByDisplayValue(/sk_/)).not.toBeInTheDocument();
    expect(screen.getByTestId("key-held")).toBeInTheDocument();
  });

  it("can forget the key it holds", async () => {
    const onSaved = vi.fn();
    render(<ApiKeyGate refused={false} hasKey onSaved={onSaved} />);

    await userEvent.click(screen.getByRole("button", { name: /forget key/i }));

    expect(readApiKey()).toBe("");
    expect(onSaved).toHaveBeenCalled();
  });

  it("says the key signs the actions, since that is what it changes", () => {
    render(<ApiKeyGate refused hasKey={false} onSaved={vi.fn()} />);

    expect(screen.getByText(/signed with the identity this key acts as/i)).toBeInTheDocument();
  });
});
