/**
 * The review screen.
 *
 * One job: let a reviewer interrogate an ordering and either stand behind it or
 * change it on the record. The gate strip is fixed at the top because "this has
 * not been approved yet" is the single most important fact on the page — an
 * unapproved comparison cannot leave the building, and the reviewer should
 * never have to hunt for that.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  approve,
  fetchAudit,
  fetchComparison,
  fetchDossiers,
  recordReview,
  type AuditRow,
  type ComparisonResult,
  type ReviewAction,
} from "./api";
import { BandAxis } from "./components/BandAxis";
import { ReviewPanel, type Flag } from "./components/ReviewPanel";

type Props = {
  comparisonId: number;
  /** Injected in tests; fetched from the API in the running app. */
  dossierFlags?: Record<string, Flag[]>;
};

export function App({ comparisonId, dossierFlags = {} }: Props) {
  const [result, setResult] = useState<ComparisonResult | null>(null);
  const [audit, setAudit] = useState<AuditRow[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [actor, setActor] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [flags, setFlags] = useState<Record<string, Flag[]>>(dossierFlags);

  const load = useCallback(async () => {
    try {
      const [comparison, log, dossiers] = await Promise.all([
        fetchComparison(comparisonId),
        fetchAudit(comparisonId),
        fetchDossiers(comparisonId),
      ]);
      setResult(comparison);
      setAudit(log);
      setFlags(
        Object.fromEntries(
          Object.entries(dossiers).map(([handle, dossier]) => [
            handle,
            dossier.red_flag_register ?? [],
          ]),
        ),
      );
      setProblem(null);
      setSelected((current) => current ?? comparison.ranked[0]?.handle ?? null);
    } catch (error) {
      setProblem(error instanceof Error ? error.message : String(error));
    }
  }, [comparisonId]);

  useEffect(() => {
    void load();
  }, [load]);

  const current = useMemo(
    () => result?.ranked.find((row) => row.handle === selected) ?? null,
    [result, selected],
  );

  async function handleAction(action: ReviewAction) {
    await recordReview(comparisonId, action);
    await load();
  }

  async function handleApprove() {
    if (!actor.trim()) {
      setProblem("Enter who you are before approving.");
      return;
    }
    try {
      await approve(comparisonId, actor);
      await load();
    } catch (error) {
      setProblem(error instanceof Error ? error.message : String(error));
    }
  }

  const pending = result?.status !== "reviewed";

  return (
    <div className="app">
      <header className={`gate ${pending ? "gate--pending" : "gate--reviewed"}`}>
        <div className="gate__state">
          <span className="gate__label">
            {pending ? "Pending review" : "Approved"}
          </span>
          <span className="gate__detail mono">
            comparison {comparisonId} · revision {result?.revision ?? 0}
          </span>
        </div>
        <p className="gate__consequence">
          {pending
            ? "Nothing can be exported until a named reviewer approves this revision."
            : "Approved for export. Any further change reopens the gate."}
        </p>
        <div className="gate__actor">
          <label htmlFor="actor">Reviewer</label>
          <input
            id="actor"
            value={actor}
            placeholder="you@example.com"
            onChange={(event) => setActor(event.target.value)}
          />
          <button type="button" onClick={handleApprove} disabled={!pending}>
            Approve revision {result?.revision ?? 0}
          </button>
        </div>
      </header>

      {problem ? (
        <p role="alert" className="app__problem">
          {problem}
        </p>
      ) : null}

      <main className="app__body">
        <section className="app__cohort">
          <h1>Where the evidence places them</h1>
          <p className="app__lede">
            Each bar is the range the evidence supports, not a single score.
            Where bars overlap, Veriquill cannot separate those candidates and
            says so rather than guessing.
          </p>
          <BandAxis
            rows={result?.ranked ?? []}
            selected={selected}
            onSelect={setSelected}
          />

          {result?.unranked.length ? (
            <div className="unranked">
              <h2>Not ranked</h2>
              {result.unranked.map((row) => (
                <p key={row.handle}>
                  <strong>{row.handle}</strong> — {row.reason}
                </p>
              ))}
            </div>
          ) : null}
        </section>

        <aside className="app__margin">
          {current ? (
            <ReviewPanel
              row={current}
              flags={flags[current.handle] ?? []}
              actor={actor}
              onAction={handleAction}
            />
          ) : (
            <p className="empty">Select a candidate to review their flags.</p>
          )}

          <section className="log">
            <h2>Audit log</h2>
            {audit.length === 0 ? (
              <p className="empty">No decisions recorded yet.</p>
            ) : (
              <ol className="log__rows">
                {audit.map((entry, index) => (
                  <li key={index}>
                    <span className="mono log__when">{entry.created_at?.slice(0, 19)}</span>
                    <span className="log__actor">{entry.actor}</span>
                    <span className="log__what">{entry.action.replace("_", " ")}</span>
                    {entry.candidate ? (
                      <span className="log__who">{entry.candidate}</span>
                    ) : null}
                    <span className="log__why">{entry.reason}</span>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </aside>
      </main>

      <footer className="app__footer">
        {result?.disclaimer ??
          "Advisory only. Veriquill supports a hiring decision and never makes one."}
      </footer>
    </div>
  );
}
