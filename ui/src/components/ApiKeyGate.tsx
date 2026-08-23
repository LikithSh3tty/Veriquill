/**
 * Asking for the API key, once, when the server wants one.
 *
 * This is not a login. There are no sessions and no users here: a key maps to
 * the identity it acts as, and that identity is what the audit log records. So
 * the screen asks for a key only after the server has actually refused a
 * request, rather than gating on load. A server with no keys configured never
 * refuses, and a reviewer there is never asked for something that does not
 * exist.
 *
 * The key is not shown once stored. Re-entering is cheap; a credential sitting
 * readable on a shared screen is not.
 */

import { useState } from "react";

import { clearApiKey, storeApiKey } from "../api";

type Props = {
  /** Set when a request came back 401, so the reason can be stated plainly. */
  refused: boolean;
  /** True once a key is held, whether or not it has been proven to work. */
  hasKey: boolean;
  onSaved: () => void;
};

export function ApiKeyGate({ refused, hasKey, onSaved }: Props) {
  const [value, setValue] = useState("");

  if (!refused && !hasKey) {
    return null;
  }

  function save(event: React.FormEvent) {
    event.preventDefault();
    if (!value.trim()) {
      return;
    }
    storeApiKey(value);
    setValue("");
    onSaved();
  }

  function forget() {
    clearApiKey();
    onSaved();
  }

  if (hasKey && !refused) {
    return (
      <div className="key-strip" data-testid="key-held">
        <span>Signed in with an API key.</span>
        <button type="button" onClick={forget}>
          Forget key
        </button>
      </div>
    );
  }

  return (
    <form className="key-strip key-strip--refused" onSubmit={save} data-testid="key-gate">
      <label htmlFor="api-key">
        {hasKey
          ? "That key was refused. Enter one this server recognises."
          : "This server needs an API key."}
      </label>
      <input
        id="api-key"
        type="password"
        autoComplete="off"
        value={value}
        placeholder="sk_..."
        onChange={(event) => setValue(event.target.value)}
      />
      <button type="submit" disabled={!value.trim()}>
        Use this key
      </button>
      <p className="key-strip__note">
        Every review action you record will be signed with the identity this key acts
        as, not with a name you type.
      </p>
    </form>
  );
}
