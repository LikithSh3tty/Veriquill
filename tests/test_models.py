from datetime import datetime, timezone

from veriquill.db import init_db, make_engine, make_session_factory, store_findings
from veriquill.findings import EvidenceRef, Finding, Severity
from veriquill.models import AnalysisRun, Candidate, FindingRecord, Repository


def test_findings_round_trip(tmp_path):
    engine = make_engine(tmp_path / "test.sqlite")
    init_db(engine)
    session_factory = make_session_factory(engine)

    with session_factory() as session:
        run = AnalysisRun(started_at=datetime.now(timezone.utc), tool_version="0.1.0")
        candidate = Candidate(handle="octocat", run=run)
        repo = Repository(full_name="octocat/hello", candidate=candidate)
        session.add(repo)
        session.flush()

        store_findings(
            session,
            repository_id=repo.id,
            findings=[
                Finding(
                    check_id="provenance.bulk_dump",
                    severity=Severity.HIGH,
                    title="Manufactured commit history",
                    rationale="Nearly all code landed in a single commit.",
                    confidence=0.8,
                    evidence=(EvidenceRef(repo="octocat/hello", commit_sha="abc123"),),
                )
            ],
        )
        session.commit()

    with session_factory() as session:
        stored = session.query(FindingRecord).one()
        assert stored.check_id == "provenance.bulk_dump"
        assert stored.severity == Severity.HIGH
        assert stored.evidence[0].commit_sha == "abc123"


def test_fingerprint_uniqueness_per_repo(tmp_path):
    from veriquill.models import RepoFingerprint

    engine = make_engine(tmp_path / "fp.sqlite")
    init_db(engine)
    session_factory = make_session_factory(engine)

    with session_factory() as session:
        session.add(
            RepoFingerprint(
                repo_full_name="a/b",
                candidate_handle="a",
                file_hashes=["h1", "h2"],
            )
        )
        session.commit()
        found = session.query(RepoFingerprint).one()
        assert found.file_hashes == ["h1", "h2"]
