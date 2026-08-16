"""Re-export of the shipped fixture builder.

The builder lives in `veriquill.eval.fixtures` because the evaluation harness
ships it as ground truth; tests keep importing it from here.
"""

from veriquill.eval.fixtures import (  # noqa: F401
    CommitSpec,
    build_repo,
    bulk_dump_history,
    burst_history,
    organic_history,
)

__all__ = [
    "CommitSpec",
    "build_repo",
    "bulk_dump_history",
    "burst_history",
    "organic_history",
]
