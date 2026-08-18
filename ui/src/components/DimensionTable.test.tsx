import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { DimensionScore } from "../api";
import { DimensionTable } from "./DimensionTable";

const measured: DimensionScore = {
  dimension: "authenticity",
  score: 0.82,
  coverage: 1,
  basis: "commit history read for 4 repositories, no authenticity flag raised",
  evidence: [{ repo: "raj/api", path: null, line: null, commit_sha: null, detail: "history read" }],
};

const unmeasured: DimensionScore = {
  dimension: "test_quality",
  score: null,
  coverage: 0,
  basis:
    "no repository was analysed in depth; only Python is analysed in depth, and no quality judgment is made about other languages in either direction",
  evidence: [],
};

describe("DimensionTable", () => {
  it("shows each measured dimension with its score", () => {
    render(<DimensionTable dimensions={[measured]} weights={{ authenticity: 0.3 }} />);

    const row = screen.getByRole("listitem");
    expect(within(row).getByText("authenticity", { selector: ".dimension__name" })).toBeInTheDocument();
    expect(within(row).getByText("0.82")).toBeInTheDocument();
  });

  it("explains what a dimension read, not just what it scored", () => {
    render(<DimensionTable dimensions={[measured]} weights={{}} />);

    expect(screen.getByText(/commit history read for 4 repositories/i)).toBeInTheDocument();
  });

  it("shows an unmeasured dimension as not measured rather than as zero", () => {
    render(<DimensionTable dimensions={[unmeasured]} weights={{}} />);

    expect(screen.getByText(/not measured/i)).toBeInTheDocument();
    expect(screen.queryByText("0.00")).not.toBeInTheDocument();
  });

  it("gives the reason a dimension could not be measured", () => {
    render(<DimensionTable dimensions={[unmeasured]} weights={{}} />);

    expect(screen.getByText(/only python is analysed in depth/i)).toBeInTheDocument();
  });

  it("shows the weight each dimension carries in this rubric", () => {
    render(<DimensionTable dimensions={[measured]} weights={{ authenticity: 0.3 }} />);

    expect(screen.getByText(/30%/)).toBeInTheDocument();
  });

  it("marks a dimension that fell below its minimum bar", () => {
    render(
      <DimensionTable
        dimensions={[measured]}
        weights={{ authenticity: 0.3 }}
        breaches={["authenticity"]}
      />,
    );

    expect(screen.getByText(/below the bar/i)).toBeInTheDocument();
  });

  it("keeps a measured dimension's bar out of the accessibility tree as decoration", () => {
    render(<DimensionTable dimensions={[measured]} weights={{}} />);

    const meter = screen.getByRole("meter", { name: /authenticity/i });
    expect(meter).toHaveAttribute("aria-valuenow", "0.82");
  });

  it("says so when there are no dimensions at all", () => {
    render(<DimensionTable dimensions={[]} weights={{}} />);

    expect(screen.getByText(/nothing was scored/i)).toBeInTheDocument();
  });
});
