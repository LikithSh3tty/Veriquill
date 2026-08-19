/**
 * The signature view: every candidate's confidence band drawn on one shared
 * axis.
 *
 * A bar chart of scores would assert an ordering the evidence may not support.
 * Drawing the interval instead makes the honest thing visible — where bands
 * overlap, the tool cannot separate those candidates, and they are bracketed
 * together as one tie group rather than listed as if the order between them
 * meant something. The point estimate is a tick, not a bar, because the single
 * number is the least certain part of the picture.
 */

import type { RankedRow } from "../api";

type Props = {
  rows: RankedRow[];
  selected?: string | null;
  onSelect?: (handle: string) => void;
};

const MARKS = [0, 0.25, 0.5, 0.75, 1];

function percent(value: number): string {
  return `${(value * 100).toFixed(2)}%`;
}

function Row({
  row,
  selected,
  onSelect,
}: {
  row: RankedRow;
  selected?: string | null;
  onSelect?: (handle: string) => void;
}) {
  const { score } = row;
  const [low, high] = score.band;
  const point = score.score ?? 0;
  const span = Math.max(high - low, 0.0001);

  return (
    <li className={`band-row${selected === row.handle ? " band-row--selected" : ""}`}>
      <button
        type="button"
        className="band-row__button"
        aria-pressed={selected === row.handle}
        onClick={() => onSelect?.(row.handle)}
      >
        <span className="band-row__rank">{row.rank}</span>
        <span className="band-row__handle">
          {row.handle}
          {row.separated_weakly ? (
            <span className="band-row__weak" title={row.separation_note}>
              narrow gap
            </span>
          ) : null}
        </span>

        <span className="band-row__track">
          {MARKS.map((mark) => (
            <span key={mark} className="band-row__gridline" style={{ left: percent(mark) }} />
          ))}
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
              style={{ left: `${((point - low) / span) * 100}%` }}
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

  return (
    <div className="band-axis">
      <div className="band-axis__scale" aria-hidden="true">
        <span className="band-axis__scale-spacer" />
        <span className="band-axis__scale-track">
          {MARKS.map((mark) => (
            <span key={mark} style={{ left: percent(mark) }}>
              {mark.toFixed(2)}
            </span>
          ))}
        </span>
      </div>

      <ol className="band-axis__rows">
        {rows.map((row) => (
          <Row key={row.handle} row={row} selected={selected} onSelect={onSelect} />
        ))}
      </ol>
    </div>
  );
}
