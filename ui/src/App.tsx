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
  addCandidate,
  approve,
  createComparison,
  deriveRubric,
  fetchAudit,
  fetchCandidates,
  fetchComparison,
  fetchDossiers,
  fetchIntakeJob,
  fetchRubrics,
  recordReview,
  type AuditRow,
  type ComparisonResult,
  type ReviewAction,
  type StoredCandidate,
} from "./api";
import { AddCandidate } from "./components/AddCandidate";
import { BandAxis } from "./components/BandAxis";
import { CohortPicker } from "./components/CohortPicker";
import { JobDescription } from "./components/JobDescription";
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
  const [candidates, setCandidates] = useState<StoredCandidate[]>([]);
  const [rubrics, setRubrics] = useState<{ name: string }[]>([]);

  // Who can be ranked is independent of whether this comparison loads. On a
  // fresh install there is no comparison yet, and intake still has to work.
  const loadRoster = useCallback(async () => {
    try {
      const [stored, available] = await Promise.all([fetchCandidates(), fetchRubrics()]);
      setCandidates(stored);
      setRubrics(available);
    } catch {
      // The roster is a convenience; its absence must not blank the review screen.
    }
  }, []);

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
    void loadRoster();
  }, [load, loadRoster]);

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
          {/* Open by default when there is nothing ranked yet: on a fresh
              install this panel is the only thing worth doing. */}
          <details className="intake-drawer" open={(result?.ranked.length ?? 0) === 0}>
            <summary>Add candidates and rank a cohort</summary>
            <AddCandidate
              onSubmit={addCandidate}
              onPoll={fetchIntakeJob}
              onAdded={() => void loadRoster()}
            />
            <JobDescription
              onDerive={deriveRubric}
              onDerived={() => void loadRoster()}
            />
            <CohortPicker
              candidates={candidates}
              rubrics={rubrics}
              onRank={createComparison}
              onRanked={(id) => {
                window.location.search = `?comparison=${id}`;
              }}
            />
          </details>

          <h1>Where the evidence places them</h1>
          <p className="app__lede">
            Each bar is the range the evidence supports, not a single score. The
            order is always explicit; a row marked “narrow gap” sits closer to the
            one above it than the evidence firmly carries, so read both before
            deciding between them.
          </p>
          {result === null && problem === null ? (
            // "Nobody has been ranked" and "the answer has not arrived yet" are
            // different statements, and the empty state must not make the first
            // one while the second is true.
            <div className="band-axis" aria-busy="true" aria-label="Loading the comparison">
              <span className="skeleton" />
              <span className="skeleton" />
              <span className="skeleton skeleton--half" />
            </div>
          ) : (
            <BandAxis
              rows={result?.ranked ?? []}
              selected={selected}
              onSelect={setSelected}
            />
          )}

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
              // Remounting per candidate clears the flag selection and the reason
              // box. A reason written about one person must never be submitted
              // against another.
              key={current.handle}
              row={current}
              flags={flags[current.handle] ?? []}
              actor={actor}
              weights={result?.rubric?.weights ?? {}}
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
                    <p className="log__head">
                      <span className="mono log__when">
                        {entry.created_at?.slice(0, 19).replace("T", " ")}
                      </span>
                      <span className="log__what">{entry.action.replace(/_/g, " ")}</span>
                      {entry.candidate ? (
                        <span className="log__who">{entry.candidate}</span>
                      ) : null}
                    </p>
                    <p className="log__why">
                      {entry.reason} <span className="log__actor">— {entry.actor}</span>
                    </p>
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
