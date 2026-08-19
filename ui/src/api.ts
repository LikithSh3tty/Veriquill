/**
 * The Veriquill API, typed.
 *
 * The server's refusals are the product here, not noise to smooth over: a
 * comparison that has not been approved returns 409, and a review action with
 * no reason returns 400. Both carry a sentence written for a human, so this
 * layer passes that sentence straight through instead of substituting one of
 * its own.
 */

const BASE = "/api";

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export type DimensionScore = {
  dimension: string;
  score: number | null;
  coverage: number;
  basis: string;
  evidence: EvidenceRef[];
};

export type EvidenceRef = {
  repo: string | null;
  path: string | null;
  line: number | null;
  commit_sha: string | null;
  detail: string | null;
};

export type CandidateScore = {
  handle: string;
  score: number | null;
  band: [number, number];
  width: number;
  confidence: "high" | "moderate" | "low";
  coverage: number;
  dimensions: DimensionScore[];
  unmeasured: string[];
  bar_breaches: string[];
};

export type RankedRow = {
  handle: string;
  rank: number;
  tie_group: number;
  score: CandidateScore;
  drivers: string[];
  machine_score?: CandidateScore | null;
  human_band?: string | null;
  override_reason?: string | null;
};

export type UnrankedRow = {
  handle: string;
  reason: string;
  score: CandidateScore;
};

export type ComparisonResult = {
  ranked: RankedRow[];
  unranked: UnrankedRow[];
  status: "pending_review" | "reviewed";
  revision: number;
  disclaimer: string;
  rubric?: { name: string; weights: Record<string, number> };
};

export type ReviewAction = {
  actor: string;
  action: "flag_dismiss" | "flag_confirm" | "band_override";
  candidate: string;
  target: string;
  reason: string;
};

export type AuditRow = {
  actor: string;
  action: string;
  candidate: string | null;
  target: string | null;
  reason: string;
  revision: number;
  created_at: string;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });

  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }

  if (!response.ok) {
    const detail =
      body && typeof body === "object" && "detail" in body
        ? String((body as { detail: unknown }).detail)
        : `request to ${path} failed with ${response.status}`;
    throw new ApiError(detail, response.status);
  }

  // A 200 carrying something that is not JSON means the request never reached
  // the API — a dev proxy serving index.html, say. Name that here, rather than
  // handing null to a caller that will dereference it three layers away.
  if (body === null || typeof body !== "object") {
    throw new ApiError(
      `${path} returned a response that was not JSON. Is the API reachable behind /api?`,
      response.status,
    );
  }

  return body as T;
}

export async function fetchComparison(id: number): Promise<ComparisonResult> {
  const payload = await request<{ result: ComparisonResult }>(`/comparisons/${id}`);
  return payload.result;
}

export async function recordReview(id: number, action: ReviewAction): Promise<void> {
  await request(`/comparisons/${id}/review`, {
    method: "POST",
    body: JSON.stringify(action),
  });
}

export async function approve(id: number, actor: string): Promise<void> {
  await request(`/comparisons/${id}/approve`, {
    method: "POST",
    body: JSON.stringify({ actor }),
  });
}

export async function fetchAudit(id: number): Promise<AuditRow[]> {
  const payload = await request<{ audit_log: AuditRow[] }>(`/comparisons/${id}/audit`);
  return payload.audit_log;
}

export async function fetchExport(id: number): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>(`/comparisons/${id}/export`);
}

export type DossierPayload = {
  handle: string;
  red_flag_register: {
    flag_id: string;
    check_id: string;
    severity: string;
    title: string;
    rationale: string;
    confidence: number;
    evidence: { repo?: string | null; path?: string | null; detail?: string | null }[];
  }[];
};

export async function fetchDossiers(id: number): Promise<Record<string, DossierPayload>> {
  const payload = await request<{ dossiers: Record<string, DossierPayload> }>(
    `/comparisons/${id}/dossiers`,
  );
  return payload.dossiers;
}
