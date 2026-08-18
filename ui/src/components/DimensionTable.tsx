/**
 * Why a candidate sits where they sit, dimension by dimension.
 *
 * The aggregate score is the least interesting number on the page. What a
 * reviewer needs is which dimension moved it and what that dimension actually
 * read, so each row carries its basis sentence rather than only a bar. A
 * dimension nobody could measure is printed as "not measured" with the reason
 * beside it, never as a zero, because a zero would read as a judgment that was
 * never made.
 */

import type { DimensionScore } from "../api";

type Props = {
  dimensions: DimensionScore[];
  weights: Record<string, number>;
  breaches?: string[];
};

function label(dimension: string): string {
  return dimension.replace(/_/g, " ");
}

export function DimensionTable({ dimensions, weights, breaches = [] }: Props) {
  if (dimensions.length === 0) {
    return <p className="empty">Nothing was scored for this candidate.</p>;
  }

  return (
    <ol className="dimensions">
      {dimensions.map((dimension) => {
        const weight = weights[dimension.dimension];
        const breached = breaches.includes(dimension.dimension);

        return (
          <li key={dimension.dimension} className="dimension">
            <p className="dimension__head">
              <span className="dimension__name">{label(dimension.dimension)}</span>
              {weight ? (
                <span className="dimension__weight mono">
                  {(weight * 100).toFixed(0)}%
                </span>
              ) : null}
              {dimension.score === null ? (
                <span className="dimension__absent">not measured</span>
              ) : (
                <span className="dimension__score mono">{dimension.score.toFixed(2)}</span>
              )}
              {breached ? <span className="dimension__breach">below the bar</span> : null}
            </p>

            {dimension.score === null ? null : (
              <span className="dimension__track">
                <span
                  className="dimension__bar"
                  role="meter"
                  aria-label={`${label(dimension.dimension)} score`}
                  aria-valuemin={0}
                  aria-valuemax={1}
                  aria-valuenow={dimension.score}
                  style={{ width: `${dimension.score * 100}%` }}
                />
              </span>
            )}

            <p className="dimension__basis">{dimension.basis}</p>
          </li>
        );
      })}
    </ol>
  );
}
