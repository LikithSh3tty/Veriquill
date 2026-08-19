/**
 * Adding a candidate by GitHub username.
 *
 * Analysis clones every public repository, so this takes minutes rather than
 * moments. The form says so before anyone starts waiting, and then reports what
 * the job is actually doing — a spinner with no elapsed reality behind it is how
 * a slow operation gets mistaken for a broken one.
 */

import { useEffect, useRef, useState } from "react";

import type { IntakeJob } from "../api";

type Props = {
  onSubmit: (
    handle: string,
    files: { resume?: File | null; linkedin?: File | null },
    jobDescription: string,
  ) => Promise<IntakeJob>;
  onPoll: (id: string) => Promise<IntakeJob>;
  onAdded: (handle: string) => void;
  pollMs?: number;
};

const PROGRESS: Record<IntakeJob["status"], string> = {
  queued: "queued",
  running: "cloning repositories and reading commit history",
  done: "stored",
  failed: "failed",
};

export function AddCandidate({ onSubmit, onPoll, onAdded, pollMs = 1500 }: Props) {
  const [handle, setHandle] = useState("");
  const [resume, setResume] = useState<File | null>(null);
  const [linkedin, setLinkedin] = useState<File | null>(null);
  const [posting, setPosting] = useState("");
  const [job, setJob] = useState<IntakeJob | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  async function watch(current: IntakeJob) {
    setJob(current);

    if (current.status === "done") {
      setBusy(false);
      onAdded(current.handle);
      return;
    }
    if (current.status === "failed") {
      setBusy(false);
      setProblem(current.error ?? `Analysing ${current.handle} failed.`);
      return;
    }

    timer.current = window.setTimeout(async () => {
      try {
        await watch(await onPoll(current.id));
      } catch (error) {
        setBusy(false);
        setProblem(error instanceof Error ? error.message : String(error));
      }
    }, pollMs);
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!handle.trim()) {
      setProblem("Enter a GitHub username.");
      return;
    }

    setProblem(null);
    setBusy(true);
    try {
      const started = await onSubmit(
        handle.trim(),
        {
          ...(resume ? { resume } : {}),
          ...(linkedin ? { linkedin } : {}),
        },
        posting.trim(),
      );
      await watch(started);
    } catch (error) {
      setBusy(false);
      setProblem(error instanceof Error ? error.message : String(error));
    }
  }

  return (
    <form className="intake" onSubmit={submit}>
      <h2>Add a candidate</h2>
      <p className="intake__wait">
        Veriquill clones every public repository on the account, so this usually
        takes a minute or two. You can leave the page; the analysis keeps running.
      </p>

      <div className="intake__field">
        <label htmlFor="handle">GitHub username</label>
        <input
          id="handle"
          value={handle}
          placeholder="octocat"
          autoComplete="off"
          spellCheck={false}
          onChange={(event) => setHandle(event.target.value)}
        />
      </div>

      <div className="intake__uploads">
        <div className="intake__field">
          <label htmlFor="resume">Résumé (optional)</label>
          <input
            id="resume"
            type="file"
            accept=".pdf,.docx,.txt,.md"
            onChange={(event) => setResume(event.target.files?.[0] ?? null)}
          />
        </div>
        <div className="intake__field">
          <label htmlFor="linkedin">LinkedIn export (optional)</label>
          <input
            id="linkedin"
            type="file"
            accept=".csv,.json"
            onChange={(event) => setLinkedin(event.target.files?.[0] ?? null)}
          />
        </div>
      </div>

      <div className="intake__field">
        <label htmlFor="posting">Job description (optional)</label>
        <textarea
          id="posting"
          rows={4}
          value={posting}
          placeholder="Paste the posting to focus a large account on the work that matters."
          onChange={(event) => setPosting(event.target.value)}
        />
        <p className="intake__hint">
          On an account with more than 20 repositories, Veriquill reads the 5 most
          relevant to this posting and records the rest as unread — which lowers
          coverage rather than counting against the candidate.
        </p>
      </div>

      <p className="intake__note">
        Documents are read once and then deleted. Date of birth, gender, marital
        status, nationality, religion, health, and photographs are removed before
        anything is parsed or stored.
      </p>

      <button type="submit" disabled={busy}>
        {busy ? "Analysing…" : "Add candidate"}
      </button>

      {job && busy ? (
        <p role="status" className="intake__status">
          <span className="intake__pulse" aria-hidden="true" />
          {job.handle}: {PROGRESS[job.status]}
        </p>
      ) : null}

      {job?.status === "done" && !busy ? (
        <p className="intake__done">{job.handle} is stored and can be ranked.</p>
      ) : null}

      {problem ? (
        <p role="alert" className="intake__problem">
          {problem}
        </p>
      ) : null}
    </form>
  );
}
