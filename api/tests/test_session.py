"""The local session.

Every test here is really about one thing: this is not a login, and it must
never become one. There is one user, they already control the machine, and the
session exists so that another process on it cannot casually drive the API.

The signing tests are pure. The behaviour tests use a real application with a
stubbed secret, because what matters is which requests get a session handed to
them and which get refused.
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from askwell import session as sessions
from askwell.app import create_app
from askwell.config import Settings

SECRET = b"0" * 32


@pytest.fixture
def client(settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    """A real application whose session secret does not need a database."""

    async def fixed_secret(_db: object) -> bytes:
        return SECRET

    monkeypatch.setattr(sessions, "secret", fixed_secret)
    monkeypatch.setattr("askwell.middleware.sessions.secret", fixed_secret)

    built = tmp_path / "out"
    built.mkdir()
    (built / "index.html").write_text("<!doctype html><title>Askwell</title>")
    return TestClient(create_app(settings.model_copy(update={"web_assets_dir": built})))


# --- signing ----------------------------------------------------------------


def test_a_session_verifies_against_the_secret_that_issued_it() -> None:
    issued = sessions.issue(SECRET)
    assert sessions.verify(SECRET, issued) is not None


def test_a_session_does_not_verify_against_a_different_secret() -> None:
    issued = sessions.issue(SECRET)
    assert sessions.verify(b"1" * 32, issued) is None


@pytest.mark.parametrize(
    "value",
    [None, "", "no-dot", "token.", ".signature", "token.wrong", "a.b.c"],
    ids=["none", "empty", "no-dot", "no-signature", "no-token", "bad-signature", "extra-dots"],
)
def test_every_malformed_value_is_simply_no_session(value: str | None) -> None:
    """One answer for every failure.

    Telling a caller *how* their cookie was wrong says more about the secret
    than a stranger should learn, and the caller does the same thing either
    way.
    """
    assert sessions.verify(SECRET, value) is None


def test_two_sessions_are_never_the_same() -> None:
    assert sessions.issue(SECRET) != sessions.issue(SECRET)


def test_only_a_prefix_of_the_token_is_ever_exposed_for_logs() -> None:
    """The token is the only thing between another local process and the
    user's material, and log files are world-readable more often than intended."""
    issued = sessions.issue(SECRET)
    token = issued.rpartition(".")[0]
    assert sessions.Session(token).short == token[:8]
    assert len(sessions.Session(token).short) == 8


# --- behaviour --------------------------------------------------------------


def test_opening_the_interface_establishes_a_session_with_no_prompt(client: TestClient) -> None:
    """docs/ux/first-run.md §5: no account, no email, no sign-in."""
    with client:
        response = client.get("/", headers={"accept": "text/html"})
    assert response.status_code == 200
    assert sessions.COOKIE_NAME in response.cookies


def test_a_data_request_without_a_session_is_refused(client: TestClient) -> None:
    with client:
        response = client.get("/network")
    assert response.status_code == 401
    assert "nothing to sign in to" in response.json()["hint"]


def test_a_data_request_with_a_session_is_answered(client: TestClient) -> None:
    with client:
        client.get("/", headers={"accept": "text/html"})
        response = client.get("/network")
    assert response.status_code == 200


def test_health_is_reachable_without_a_session(client: TestClient) -> None:
    """The surface someone with a broken install needs most.

    It carries component states rather than any of the user's material, and
    locking it would make Askwell hardest to diagnose in exactly the situation
    where diagnosis matters. A decision, not an oversight — and the only one.
    """
    with client:
        assert client.get("/health").status_code == 200


def test_the_exemption_list_stays_at_one_entry() -> None:
    """Its existing at all is the risk. Each addition needs a reason."""
    from askwell.middleware import OPEN_PATHS

    assert OPEN_PATHS == frozenset({"/health"})


def test_a_forged_cookie_is_refused(client: TestClient) -> None:
    with client:
        response = client.get("/network", headers={"cookie": f"{sessions.COOKIE_NAME}=abc.def"})
    assert response.status_code == 401


def test_a_request_from_another_origin_is_refused(client: TestClient) -> None:
    """Another site's page reaching into Askwell using the user's own cookie."""
    with client:
        client.get("/", headers={"accept": "text/html"})
        response = client.get("/network", headers={"origin": "https://evil.example"})
    assert response.status_code == 403
    assert "its own interface" in response.json()["error"]


def test_a_request_with_no_origin_is_not_treated_as_cross_origin(client: TestClient) -> None:
    """curl, and browser navigations, send no Origin. Neither is another site."""
    with client:
        assert client.get("/", headers={"accept": "text/html"}).status_code == 200


def test_two_windows_both_work(client: TestClient) -> None:
    """There is one user. Two windows is one person with two windows."""
    with client:
        first = client.get("/", headers={"accept": "text/html"})
        second_client = TestClient(client.app)
        with second_client:
            second = second_client.get("/", headers={"accept": "text/html"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.cookies[sessions.COOKIE_NAME] != second.cookies[sessions.COOKIE_NAME]


def test_a_cleared_session_store_gets_a_new_one_silently(client: TestClient) -> None:
    with client:
        client.get("/", headers={"accept": "text/html"})
        client.cookies.clear()
        response = client.get("/", headers={"accept": "text/html"})

    assert response.status_code == 200
    assert sessions.COOKIE_NAME in response.cookies


def test_there_is_no_sign_in_anywhere() -> None:
    """The absence is the feature.

    A password field, a login route or a token endpoint appearing here would
    mean the product had grown a concept it is defined by not having.

    Comments and strings are stripped with `tokenize` rather than filtered by
    hand. An earlier version skipped lines *containing* a triple quote, which
    is not the same as lines *inside* a docstring — and it failed on the
    session module's own prose explaining that none of this exists. A test that
    cannot tell a denial from a use gets deleted the first time it is wrong.
    """
    import io
    import tokenize

    root = Path(__file__).resolve().parents[1] / "src" / "askwell"
    forbidden = re.compile(r"\b(password_hash|login|sign_?in|logout|bcrypt|argon2)\b", re.I)
    offenders = []

    for path in sorted(root.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        try:
            tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
        except tokenize.TokenError:  # pragma: no cover - syntax is checked elsewhere
            continue
        for token in tokens:
            if token.type in {tokenize.COMMENT, tokenize.STRING}:
                continue
            if forbidden.search(token.string):
                offenders.append(f"{path.name}:{token.start[0]} {token.string!r}")

    assert not offenders, f"sign-in machinery has appeared: {offenders}"
