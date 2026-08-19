/**
 * Ranking against the job you are actually hiring for.
 *
 * A recruiter has a posting, not a weights table. This turns the posting into a
 * rubric and shows the phrases that raised each dimension, so the weighting can
 * be checked before anyone is ranked against it — and so a candidate can be told
 * why security counted for a third of their score.
 *
 * No model reads the description. The mapping is a table of phrases, printed
 * here, which is the only kind of weighting a rejected candidate could argue
 * with.
 */

import { useState } from "react";

import type { DerivedRubric } from "../api";

type Props = {
  onDerive: (name: string, text: string) => Promise<DerivedRubric>;
  onDerived: (rubricName: string) => void;
};

function label(dimension: string): string {
  return dimension.replace(/_/g, " ");
}

export function JobDescription({ onDerive, onDerived }: Props) {
  const [name, setName] = useState("");
  const [text, setText] = useState("");
  const [result, setResult] = useState<DerivedRubric | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function derive() {
    if (!text.trim()) {
      setProblem("Paste the job description first.");
      return;
    }

    setProblem(null);
    setBusy(true);
    try {
      const derived = await onDerive(name.trim() || "job", text.trim());
      setResult(derived);
      onDerived(derived.rubric.name);
    } catch (error) {
      setProblem(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  const weights = result ? Object.entries(result.rubric.weights) : [];

  return (
    <section className="jd">
      <h2>Rank against a job description</h2>
      <p className="jd__lede">
        Paste the posting. Veriquill raises the dimensions it asks for and shows
        the phrases that did it, so you can check the weighting before it ranks
        anyone.
      </p>

      <div className="jd__field">
        <label htmlFor="jd-name">Name for this role</label>
        <input
          id="jd-name"
          value={name}
          placeholder="secure-backend"
          onChange={(event) => setName(event.target.value)}
        />
      </div>

      <div className="jd__field">
        <label htmlFor="jd-text">Job description</label>
        <textarea
          id="jd-text"
          rows={7}
          value={text}
          placeholder="Paste the posting here."
          onChange={(event) => setText(event.target.value)}
        />
      </div>

      <button type="button" onClick={derive} disabled={busy}>
        {busy ? "Deriving…" : "Derive rubric"}
      </button>

      {problem ? (
        <p role="alert" className="jd__problem">
          {problem}
        </p>
      ) : null}

      {result ? (
        <div className="jd__result">
          <p className="jd__note">{result.derivation.note}</p>

          <ul className="jd__weights">
            {weights.map(([dimension, weight]) => {
              const phrases = result.derivation.emphases[dimension];
              return (
                <li key={dimension} className={phrases ? "jd__weight jd__weight--raised" : "jd__weight"}>
                  <span className="jd__dimension">{label(dimension)}</span>
                  <span className="jd__value">{Math.round(weight * 100)}%</span>
                  {phrases ? (
                    <span className="jd__phrases">
                      raised by {phrases.map((p) => `“${p}”`).join(", ")}
                    </span>
                  ) : (
                    <span className="jd__phrases jd__phrases--default">default weight</span>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
