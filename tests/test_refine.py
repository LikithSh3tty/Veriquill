import json
from types import SimpleNamespace

from veriquill.claims.documents import Document
from veriquill.claims.models import Claim, ClaimKind, ClaimSource
from veriquill.claims.refine import ClaimRefiner
from veriquill.config import Settings

DOC = Document(
    name="resume.txt",
    lines=(
        "EXPERIENCE",
        "Shipped the payments service end to end.",
        "Mentored two junior engineers.",
    ),
)


class FakeMessages:
    def __init__(self, payload, stop_reason="end_turn"):
        self._payload = payload
        self._stop_reason = stop_reason
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            stop_reason=self._stop_reason,
            content=[SimpleNamespace(type="text", text=json.dumps(self._payload))],
        )


class FakeClient:
    def __init__(self, payload, stop_reason="end_turn"):
        self.messages = FakeMessages(payload, stop_reason)


def _settings(tmp_path) -> Settings:
    return Settings(github_token="t", data_dir=tmp_path)


def test_refiner_emits_claims_grounded_in_the_document(tmp_path):
    client = FakeClient(
        {
            "claims": [
                {
                    "kind": "achievement",
                    "text": "Shipped the payments service",
                    "subject": "payments",
                    "excerpt": "Shipped the payments service end to end.",
                }
            ]
        }
    )
    refiner = ClaimRefiner(_settings(tmp_path), client=client)

    claims = refiner.refine(DOC, existing=[])

    assert len(claims) == 1
    assert claims[0].source.locator == "line 2"
    assert claims[0].kind is ClaimKind.ACHIEVEMENT


def test_a_claim_whose_excerpt_is_not_in_the_document_is_dropped(tmp_path):
    """The LLM phrases findings; it does not get to invent source text.

    A claim the model attributes to text that does not appear in the document
    cannot be cited back to the candidate, so it is discarded rather than
    surfaced with a fabricated locator.
    """
    client = FakeClient(
        {
            "claims": [
                {
                    "kind": "role",
                    "text": "Was CTO of a unicorn",
                    "excerpt": "Served as Chief Technology Officer",
                }
            ]
        }
    )
    refiner = ClaimRefiner(_settings(tmp_path), client=client)

    assert refiner.refine(DOC, existing=[]) == []


def test_claims_already_found_structurally_are_not_duplicated(tmp_path):
    existing = [
        Claim(
            kind=ClaimKind.ACHIEVEMENT,
            text="Shipped the payments service end to end.",
            source=ClaimSource(
                document="resume.txt",
                locator="line 2",
                excerpt="Shipped the payments service end to end.",
            ),
        )
    ]
    client = FakeClient(
        {
            "claims": [
                {
                    "kind": "achievement",
                    "text": "Shipped the payments service end to end.",
                    "excerpt": "Shipped the payments service end to end.",
                }
            ]
        }
    )
    refiner = ClaimRefiner(_settings(tmp_path), client=client)

    assert refiner.refine(DOC, existing=existing) == []


def test_a_refusal_returns_no_claims_rather_than_raising(tmp_path):
    client = FakeClient({"claims": []}, stop_reason="refusal")
    refiner = ClaimRefiner(_settings(tmp_path), client=client)

    assert refiner.refine(DOC, existing=[]) == []


def test_malformed_model_output_returns_no_claims(tmp_path):
    class Broken(FakeClient):
        def __init__(self):
            super().__init__({})
            self.messages.create = lambda **kw: SimpleNamespace(
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text="not json at all")],
            )

    refiner = ClaimRefiner(_settings(tmp_path), client=Broken())
    assert refiner.refine(DOC, existing=[]) == []


def test_the_request_uses_the_configured_model_and_no_sampling_params(tmp_path):
    client = FakeClient({"claims": []})
    settings = _settings(tmp_path)
    ClaimRefiner(settings, client=client).refine(DOC, existing=[])

    sent = client.messages.calls[0]
    assert sent["model"] == settings.claim_model
    # Sampling parameters are rejected by current models; never send them.
    assert "temperature" not in sent
    assert "top_p" not in sent
    assert "top_k" not in sent


def test_refiner_without_credentials_is_unavailable_and_returns_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "veriquill.claims.refine.ClaimRefiner._build_client",
        lambda self: None,
    )
    refiner = ClaimRefiner(_settings(tmp_path))

    assert refiner.available is False
    assert refiner.refine(DOC, existing=[]) == []
