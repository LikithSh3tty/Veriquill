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
const KEY_STORAGE = "veriquill.apiKey";

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }

  /** A 401 is a missing or wrong key, which the screen can act on. */
  get isUnauthorized(): boolean {
    return this.status === 401;
  }
}

/**
 * The API key, if this browser has one.
 *
 * It lives in localStorage rather than in a cookie, because the server
 * authenticates a header and a cookie would be sent on every request whether or
 * not it was wanted. Storage can throw outright in a private window or with
 * site data blocked, so every access is guarded and a failure reads the same as
 * having no key: the screen asks for one.
 */
export function readApiKey(): string {
  try {
    return window.localStorage.getItem(KEY_STORAGE) ?? "";
  } catch {
    return "";
  }
}

export function storeApiKey(key: string): void {
  try {
    const trimmed = key.trim();
    if (trimmed) {
      window.localStorage.setItem(KEY_STORAGE, trimmed);
    } else {
      window.localStorage.removeItem(KEY_STORAGE);
    }
  } catch {
    // A browser that will not store it still works for this session, because
    // the key is read back through the same accessor on every request.
  }
}

export function clearApiKey(): void {
  storeApiKey("");
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
  separated_weakly?: boolean;
  separation_note?: string;
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
  // FormData sets its own multipart boundary. Forcing a JSON content type onto
  // an upload strips that boundary and the server sees a malformed body.
  const isForm = init?.body instanceof FormData;

  const headers: Record<string, string> = {};
  if (!isForm) {
    headers["Content-Type"] = "application/json";
  }
  // Sent whenever we have one. A server with no keys configured ignores it, so
  // the same bundle works against an open API and a protected one.
  const key = readApiKey();
  if (key) {
    headers.Authorization = `Bearer ${key}`;
  }
  Object.assign(headers, (init?.headers as Record<string, string>) ?? {});

  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers,
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

export type IntakeJob = {
  id: string;
  handle: string;
  status: "queued" | "running" | "done" | "failed";
  error: string | null;
  dossier_id: number | null;
  created_at: string;
  finished_at: string | null;
};

export type StoredCandidate = {
  handle: string;
  dossier_id: number;
  stored_at: string;
  flags: number;
};

/** Start analysing a candidate. Returns a job to poll, not a finished dossier. */
export async function addCandidate(
  handle: string,
  files: { resume?: File | null; linkedin?: File | null } = {},
  jobDescription = "",
): Promise<IntakeJob> {
  const form = new FormData();
  form.append("handle", handle);
  // A large account is read most-relevant-first, so the posting has to travel
  // with the request: selection happens before any repository is cloned.
  if (jobDescription.trim()) form.append("job_description", jobDescription.trim());
  if (files.resume) form.append("resume", files.resume);
  if (files.linkedin) form.append("linkedin", files.linkedin);

  // FormData sets its own multipart boundary; forcing a Content-Type breaks it.
  const payload = await request<{ job: IntakeJob }>("/candidates", {
    method: "POST",
    body: form,
    headers: {},
  });
  return payload.job;
}

export async function fetchIntakeJob(id: string): Promise<IntakeJob> {
  const payload = await request<{ job: IntakeJob }>(`/candidates/jobs/${id}`);
  return payload.job;
}

export async function fetchCandidates(): Promise<StoredCandidate[]> {
  const payload = await request<{ candidates: StoredCandidate[] }>("/candidates");
  // A response missing the field is a contract mismatch, not a reason to hand a
  // component undefined and let it crash the screen.
  return payload.candidates ?? [];
}

export async function createComparison(
  rubric: string,
  candidates: string[],
): Promise<number> {
  const payload = await request<{ comparison_id: number }>("/comparisons", {
    method: "POST",
    body: JSON.stringify({ rubric, candidates }),
  });
  return payload.comparison_id;
}

export async function fetchRubrics(): Promise<{ name: string }[]> {
  const payload = await request<{ rubrics: { name: string }[] }>("/rubrics");
  return payload.rubrics ?? [];
}

export type DerivedRubric = {
  rubric: {
    name: string;
    version: number;
    weights: Record<string, number>;
    minimum_bars: Record<string, number>;
  };
  derivation: {
    emphases: Record<string, string[]>;
    note: string;
  };
};

/** Turn a job description into a stored rubric, with the phrases that shaped it. */
export async function deriveRubric(name: string, text: string): Promise<DerivedRubric> {
  return request<DerivedRubric>("/rubrics/from-job-description", {
    method: "POST",
    body: JSON.stringify({ name, text }),
  });
}
