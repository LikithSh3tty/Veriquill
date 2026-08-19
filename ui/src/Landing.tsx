/**
 * The public page.
 *
 * Persuade mode, but the visitor is a hiring lead in a regulated context, so the
 * persuasion is evidence rather than enthusiasm: the page opens on the actual
 * artifact — a cohort where three candidates cannot be separated — and states the
 * limits as plainly as the capabilities. A tool that checks other people's claims
 * has to be checkable itself.
 */

const DIMENSIONS = [
  {
    name: "authenticity",
    weight: "30%",
    reads: "commit history, cadence, fork origin, who authored what",
  },
  {
    name: "code quality",
    weight: "20%",
    reads: "complexity, lint compliance, modules nothing imports",
  },
  {
    name: "claim corroboration",
    weight: "20%",
    reads: "résumé and profile claims against repository evidence",
  },
  {
    name: "test quality",
    weight: "15%",
    reads: "whether assertions mean anything, not how many exist",
  },
  {
    name: "security",
    weight: "10%",
    reads: "security-hygiene findings in authored code",
  },
  {
    name: "breadth",
    weight: "5%",
    reads: "repositories holding code the candidate actually wrote",
  },
];

const COHORT = [
  { handle: "nadia", low: 0.79, high: 0.89, tied: true },
  { handle: "priya", low: 0.76, high: 0.86, tied: true },
  { handle: "omar", low: 0.73, high: 0.83, tied: true },
  { handle: "raj", low: 0.47, high: 0.57, tied: false },
];

const MARKS = [0, 0.25, 0.5, 0.75, 1];

export function Landing() {
  return (
    <div className="page">
      <header className="masthead">
        <span className="masthead__mark">Veriquill</span>
        <nav className="masthead__nav">
          <a href="#how">What it reads</a>
          <a href="#limits">Limits</a>
          <a href="/review.html?comparison=1">Open the review screen</a>
        </nav>
      </header>

      <main>
        <section className="hero">
          <h1 className="hero__claim">
            Three of these four candidates cannot be told apart.
          </h1>

          <figure className="specimen">
            <figcaption className="specimen__caption">
              A ranked cohort. Each bar is the range the evidence supports, not a
              score.
            </figcaption>

            <div className="specimen__axis" aria-hidden="true">
              <span className="specimen__axis-spacer" />
              <span className="specimen__axis-track">
                {MARKS.map((mark) => (
                  <span key={mark} style={{ left: `${mark * 100}%` }}>
                    {mark.toFixed(2)}
                  </span>
                ))}
              </span>
              <span />
            </div>

            <ol className="specimen__rows">
              {COHORT.map((row) => (
                <li
                  key={row.handle}
                  className={
                    row.tied ? "specimen__row specimen__row--tied" : "specimen__row"
                  }
                >
                  <span className="specimen__handle">{row.handle}</span>
                  <span className="specimen__track">
                    <span
                      className="specimen__band"
                      style={{
                        left: `${row.low * 100}%`,
                        width: `${(row.high - row.low) * 100}%`,
                      }}
                    />
                  </span>
                  <span className="specimen__readout">
                    {row.low.toFixed(2)} – {row.high.toFixed(2)}
                  </span>
                </li>
              ))}
            </ol>

            <p className="specimen__tie">
              The first three overlap. Veriquill reports them as tied rather than
              inventing an order the evidence does not support.
            </p>
          </figure>

          <p className="hero__lede">
            Veriquill checks whether a portfolio is genuinely the candidate's own
            iterative work, evaluates the code in it, and reconciles what they claim
            against what their commits show. Every finding cites the commit, file, or
            line that produced it. It supports a hiring decision and never makes one.
          </p>
        </section>

        <section className="section" id="how">
          <h2 className="section__title">What it reads</h2>
          <p className="section__lede">
            A recruiter sets the weights. Veriquill fixes the dimensions, because
            each one is backed by a check that produces evidence — a dimension
            nobody can evidence is an opinion with a number attached.
          </p>

          <table className="rubric">
            <thead>
              <tr>
                <th scope="col">Dimension</th>
                <th scope="col">Default weight</th>
                <th scope="col">What it reads</th>
              </tr>
            </thead>
            <tbody>
              {DIMENSIONS.map((row) => (
                <tr key={row.name}>
                  <th scope="row">{row.name}</th>
                  <td className="rubric__weight">{row.weight}</td>
                  <td>{row.reads}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="section">
          <h2 className="section__title">Four rules the tool cannot break</h2>
          <dl className="rules">
            <div className="rule">
              <dt>Thin evidence widens the band. It never lowers the score.</dt>
              <dd>
                A dimension nobody could measure is dropped from the weighting and
                listed with the reason. A candidate whose repositories are private
                reads as “we could not tell”, not as weak.
              </dd>
            </div>
            <div className="rule">
              <dt>A flag is a question, never proof.</dt>
              <dd>
                A bulk-dump history looks identical whether a codebase was fabricated
                or simply developed locally and imported once. The register says so,
                next to the flag.
              </dd>
            </div>
            <div className="rule">
              <dt>Nothing leaves until a named human approves it.</dt>
              <dd>
                A comparison is created pending review and cannot be exported.
                Approval covers exactly the revision it saw; any later change reopens
                the gate.
              </dd>
            </div>
            <div className="rule">
              <dt>An override annotates the result. It never replaces it.</dt>
              <dd>
                Dismissals and band overrides are recorded with the actor and the
                reason. The export carries what Veriquill said beside what the human
                changed, and replaying the log reconstructs any state it has held.
              </dd>
            </div>
          </dl>
        </section>

        <section className="section" id="limits">
          <h2 className="section__title">What it does not do</h2>
          <ul className="limits">
            <li>
              It never infers a protected attribute. Where a document states one
              outright — date of birth, marital status, nationality, religion, health,
              a photograph — the value is removed before parsing, before any model
              sees it, and before anything is stored.
            </li>
            <li>
              It analyses Python in depth. Other languages are detected and counted,
              and the output says so rather than implying a clean bill of health.
            </li>
            <li>
              Its bias audit needs group labels you supply from your own records.
              Without them it reports evidence-coverage disparity, which needs no
              protected data, and names what it could not measure.
            </li>
            <li>
              Its self-audit is not an independent bias audit. Jurisdictions such as
              New York City require one, and nothing here replaces it.
            </li>
          </ul>
        </section>

        <section className="section closing">
          <h2 className="section__title">Open the review screen</h2>
          <p className="section__lede">
            The dashboard runs against a local API. Rank a cohort, dismiss a flag
            with a reason, approve a revision, and read the audit log it writes.
          </p>
          <a className="cta" href="/review.html?comparison=1">
            Open the review screen
          </a>
        </section>
      </main>

      <footer className="page__footer">
        <p>
          Veriquill is advisory. It does not auto-reject, does not auto-hire, and
          does not treat a flag as proof of wrongdoing.
        </p>
      </footer>
    </div>
  );
}
