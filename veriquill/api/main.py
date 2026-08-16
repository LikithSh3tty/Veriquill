"""HTTP surface.

This layer holds no analysis logic. It starts runs and returns their results.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from veriquill import __version__
from veriquill.config import get_settings
from veriquill.pipeline import analyse_candidate

app = FastAPI(title="Veriquill", version=__version__)

# In-process run store. M1 is a single-machine pipeline; persistence of runs
# across processes arrives with the dossier milestone.
_RUNS: dict[str, dict[str, Any]] = {}


class AnalyseRequest(BaseModel):
    handle: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.post("/analyse")
async def start_analysis(request: AnalyseRequest) -> dict[str, str]:
    run_id = uuid4().hex
    settings = get_settings()
    summary = await analyse_candidate(request.handle, settings)
    _RUNS[run_id] = summary.to_dict()
    return {"run_id": run_id, "status": "complete"}


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    summary = _RUNS.get(run_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {"run_id": run_id, "summary": summary}
