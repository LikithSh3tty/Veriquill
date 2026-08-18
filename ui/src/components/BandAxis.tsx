/**
 * The signature view: every candidate's confidence band drawn on one shared
 * axis.
 *
 * A bar chart of scores would assert an ordering the evidence may not support.
 * Drawing the interval instead makes the honest thing visible — when two bands
 * overlap, you can see that the tool cannot separate those candidates, which is
 * exactly what the tie groups mean. The point estimate is a tick, not a bar,
 * because the number is the least certain part of the picture.
 */

import type { RankedRow } from "../api";

type Props = {
  rows: RankedRow[];
  selected?: string | null;
  onSelect?: (handle: string) => void;
};

function percent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export function BandAxis({ rows, selected, onSelect }: Props) {
  if (rows.length === 0) {
    return (
      <p className="empty">
        No candidate has been ranked yet. Rank a cohort to see how far apart the
        evidence actually places them.
      </p>
    );
  }

  const tieSizes = new Map<number, number>();
  for (const row of rows) {
    tieSizes.set(row.tie_group, (tieSizes.get(row.tie_group) ?? 0) + 1);
  }

  return (
    <div className="band-axis">
      <div className="band-axis__scale" aria-hidden="true">
        {[0, 0.25, 0.5, 0.75, 1].map((mark) => (
          <span key={mark} style={{ left: percent(mark) }}>
            {mark.toFixed(2)}
          </span>
        ))}
      </div>

      <ol className="band-axis__rows">
        {rows.map((row) => {
          const { score } = row;
          const [low, high] = score.band;
          const tied = (tieSizes.get(row.tie_group) ?? 1) > 1;
          const point = score.score ?? 0;

          return (
            <li
              key={row.handle}
              className={`band-row${selected === row.handle ? " band-row--selected" : ""}`}
            >
              <button
                type="button"
                className="band-row__button"
                aria-pressed={selected === row.handle}
                onClick={() => onSelect?.(row.handle)}
              >
                <span className="band-row__rank">{row.rank}</span>
                <span className="band-row__handle">{row.handle}</span>
                {tied ? <span className="band-row__tie">tied</span> : null}

                <span className="band-row__track">
                  <span
                    className="band-row__band"
                    role="meter"
                    aria-label={`${row.handle} confidence band`}
                    aria-valuemin={Number(low.toFixed(2))}
                    aria-valuemax={Number(high.toFixed(2))}
                    aria-valuenow={Number(point.toFixed(2))}
                    style={{ left: percent(low), width: percent(high - low) }}
                  >
                    <span
                      className="band-row__point"
                      style={{ left: `${((point - low) / Math.max(high - low, 0.0001)) * 100}%` }}
                    />
                  </span>
                </span>

                <span className="band-row__readout">
                  <span className="band-row__interval">
                    {low.toFixed(2)} – {high.toFixed(2)}
                  </span>
                  <span className="band-row__coverage">
                    coverage {(score.coverage * 100).toFixed(0)}%
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
