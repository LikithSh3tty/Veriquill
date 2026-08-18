/**
 * Where a human writes in the margin.
 *
 * Everything the machine said stays in black and stays put. A reviewer's
 * dismissal or override is recorded beside it in blue, with a reason, because
 * the audit log has to answer "who decided this, and why" months later. The
 * reason requirement is enforced on the server; it is enforced here too so the
 * reviewer finds out before a round trip, never instead of one.
 */

import { useState } from "react";

import type { RankedRow, ReviewAction } from "../api";
import { DimensionTable } from "./DimensionTable";

export type Flag = {
  flag_id: string;
  check_id: string;
  severity: string;
  title: string;
  rationale: string;
  confidence: number;
  evidence: { repo?: string | null; path?: string | null; detail?: string | null }[];
};

type Props = {
  row: RankedRow;
  flags: Flag[];
  actor: string;
  weights?: Record<string, number>;
  onAction: (action: ReviewAction) => Promise<void>;
};

export function ReviewPanel({ row, flags, actor, weights = {}, onAction }: Props) {
  const [reason, setReason] = useState("");
  const [target, setTarget] = useState(flags[0]?.flag_id ?? "");
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function send(action: ReviewAction["action"], flagId: string) {
    if (!actor.trim()) {
      setProblem("Enter who you are before recording a decision.");
      return;
    }
    if (!reason.trim()) {
      setProblem("Give a reason. It goes in the audit log next to your name.");
      return;
    }

    setProblem(null);
    setBusy(true);
    try {
      await onAction({
        actor,
        action,
        candidate: row.handle,
        target: flagId,
        reason: reason.trim(),
      });
      setReason("");
    } catch (error) {
      setProblem(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="review">
      <header className="review__header">
        <h2>{row.handle}</h2>
        <p className="review__machine">
          Veriquill scored <strong>{row.score.score?.toFixed(2) ?? "—"}</strong>{" "}
          <span className="mono">
            ({row.score.band[0].toFixed(2)} – {row.score.band[1].toFixed(2)})
          </span>
          , confidence {row.score.confidence}.
        </p>
        {row.human_band ? (
          <p className="review__override">
            Reviewer set this to <strong>{row.human_band}</strong> — {row.override_reason}
          </p>
        ) : null}
      </header>

      <h3 className="review__subhead">What was measured</h3>
      <DimensionTable
        dimensions={row.score.dimensions}
        weights={weights}
        breaches={row.score.bar_breaches}
      />

      <h3 className="review__subhead">Flags</h3>
      {flags.length === 0 ? (
        <p className="empty">No flags were raised for this candidate.</p>
      ) : (
        <ul className="review__flags">
          {flags.map((flag) => (
            <li key={flag.flag_id} className={`flag flag--${flag.severity}`}>
              <label className="flag__select">
                <input
                  type="radio"
                  name="flag"
                  value={flag.flag_id}
                  checked={target === flag.flag_id}
                  onChange={() => setTarget(flag.flag_id)}
                />
                <span className="flag__severity">{flag.severity}</span>
                <span className="flag__title">{flag.title}</span>
              </label>
              <p className="flag__rationale">{flag.rationale}</p>
              <ul className="flag__evidence">
                {flag.evidence.map((ref, index) => (
                  <li key={index} className="mono">
                    {[ref.repo, ref.path, ref.detail].filter(Boolean).join(" · ")}
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}

      <div className="review__form">
        <label htmlFor="reason">Reason</label>
        <textarea
          id="reason"
          value={reason}
          rows={2}
          placeholder="Why this flag does or does not stand"
          onChange={(event) => setReason(event.target.value)}
        />

        <div className="review__actions">
          <button type="button" disabled={busy || !target} onClick={() => send("flag_dismiss", target)}>
            Dismiss flag
          </button>
          <button type="button" disabled={busy || !target} onClick={() => send("flag_confirm", target)}>
            Confirm flag
          </button>
        </div>

        {problem ? (
          <p role="alert" className="review__problem">
            {problem}
          </p>
        ) : null}
      </div>
    </section>
  );
}
