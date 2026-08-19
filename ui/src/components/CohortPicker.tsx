/**
 * Choosing who to compare, and against which rubric.
 *
 * Ranking is cheap — it reads stored dossiers and makes no network call of its
 * own — so this is an ordinary form rather than a job. The empty states name the
 * thing to do next, because a reviewer arriving at an empty tool should not have
 * to guess whether it is broken or simply unused.
 */

import { useState } from "react";

import type { StoredCandidate } from "../api";

type Props = {
  candidates: StoredCandidate[];
  rubrics: { name: string }[];
  onRank: (rubric: string, handles: string[]) => Promise<number>;
  onRanked: (comparisonId: number) => void;
};

export function CohortPicker({ candidates = [], rubrics = [], onRank, onRanked }: Props) {
  const [selected, setSelected] = useState<string[]>([]);
  // The roster loads after this renders, so the choice cannot be frozen at
  // mount: hold only an explicit pick and fall back to whatever arrived.
  const [picked, setPicked] = useState<string | null>(null);
  const rubric = picked ?? rubrics[0]?.name ?? "";
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function toggle(handle: string) {
    setSelected((current) =>
      current.includes(handle)
        ? current.filter((h) => h !== handle)
        : [...current, handle],
    );
  }

  async function rank() {
    if (selected.length === 0) {
      setProblem("Select at least one candidate to rank.");
      return;
    }
    if (!rubric) {
      setProblem("Store a rubric first: veriquill rubric-add rubric.json");
      return;
    }

    setProblem(null);
    setBusy(true);
    try {
      // Keep the order the list shows, not the order they were clicked.
      const handles = candidates
        .map((c) => c.handle)
        .filter((handle) => selected.includes(handle));
      onRanked(await onRank(rubric, handles));
    } catch (error) {
      setProblem(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="cohort">
      <h2>Rank a cohort</h2>

      {rubrics.length === 0 ? (
        <p className="empty">
          No rubric is stored yet. Add one with <code>veriquill rubric-add rubric.json</code>,
          then reload.
        </p>
      ) : (
        <div className="cohort__rubric">
          <label htmlFor="rubric">Rubric</label>
          <select
            id="rubric"
            value={rubric}
            onChange={(event) => setPicked(event.target.value)}
          >
            {rubrics.map((r) => (
              <option key={r.name} value={r.name}>
                {r.name}
              </option>
            ))}
          </select>
        </div>
      )}

      {candidates.length === 0 ? (
        <p className="empty">
          Nobody has been analysed yet. Add a candidate by GitHub username above.
        </p>
      ) : (
        <ul className="cohort__list">
          {candidates.map((candidate) => (
            <li key={candidate.handle}>
              <label>
                <input
                  type="checkbox"
                  checked={selected.includes(candidate.handle)}
                  onChange={() => toggle(candidate.handle)}
                />
                <span className="cohort__handle">{candidate.handle}</span>
                <span className="cohort__flags">
                  {candidate.flags === 1 ? "1 flag" : `${candidate.flags} flags`}
                </span>
              </label>
            </li>
          ))}
        </ul>
      )}

      <button type="button" onClick={rank} disabled={busy || candidates.length === 0}>
        {busy ? "Ranking…" : `Rank ${selected.length || ""} selected`.trim()}
      </button>

      {problem ? (
        <p role="alert" className="cohort__problem">
          {problem}
        </p>
      ) : null}
    </section>
  );
}
