"""Redis users, one per service — `M8-FIX-SEC-177`, issue #730.

The egress proxy opens a route off the machine for whatever grant Redis
holds, so who may write an `askwell:egress:*` key is C1's enforcement, not
housekeeping. Two halves:

- **Unmarked**: `deploy/redis/users.acl` and `compose.yaml` say what the
  ticket says, read as text, on every push with no network.
- **`requires_db`**: a real Redis, started from that file, refuses what it
  should. Run by `scripts/dev.sh test-db` against the stack's own Redis (CI
  starts one the same way). A static reading of an ACL file is a claim about
  Redis; only Redis refusing is evidence. These fail, not skip, without it.
"""

import os
import re
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import redis.asyncio as redis
from pydantic import SecretStr
from redis.exceptions import AuthenticationError, NoPermissionError

from askwell import egress
from askwell.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
ACL = REPO_ROOT / "deploy" / "redis" / "users.acl"
START = REPO_ROOT / "deploy" / "redis" / "start.sh"
COMPOSE = REPO_ROOT / "compose.yaml"

GRANT_PATTERNS = {
    "askwell:egress:permitted_host",
    "askwell:egress:grant:*",
    "askwell:egress:conversation:*",
}


@dataclass
class Rules:
    """One user's line, split into the root rules and any selectors."""

    enabled: bool
    commands: set[str] = field(default_factory=set)
    keys: dict[str, str] = field(default_factory=dict)  # pattern -> R, W or RW
    selectors: list["Rules"] = field(default_factory=list)
    raw: list[str] = field(default_factory=list)


def _parse_rules(tokens: list[str]) -> Rules:
    rules = Rules(enabled="on" in tokens, raw=tokens)
    for token in tokens:
        if token.startswith(("+", "-")):
            rules.commands.add(token)
        elif token.startswith("~"):
            rules.keys[token[1:]] = "RW"
        elif match := re.fullmatch(r"%(R|W|RW)~(.+)", token):
            rules.keys[match.group(2)] = match.group(1)
    return rules


def _users() -> dict[str, Rules]:
    users: dict[str, Rules] = {}
    for line in ACL.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        selectors = re.findall(r"\(([^)]*)\)", line)
        root = re.sub(r"\([^)]*\)", "", line).split()
        assert root[0] == "user", line
        rules = _parse_rules(root[2:])
        rules.selectors = [_parse_rules(s.split()) for s in selectors]
        users[root[1]] = rules
    return users


def _writes(rules: Rules, pattern: str) -> bool:
    return "W" in rules.keys.get(pattern, "") or "W" in rules.keys.get("*", "")


# --- the file, read as text ---------------------------------------------------


def test_there_is_one_user_per_service_that_connects_and_nobody_else() -> None:
    """`voice` and `inference-bridge` never open Redis, so neither has a user
    — a permission it does not use is one the ticket forbids."""
    assert set(_users()) == {"default", "healthcheck", "api", "worker", "proxy"}


def test_an_unauthenticated_connection_can_do_nothing() -> None:
    default = _users()["default"]
    assert not default.enabled
    assert default.commands == {"-@all"}
    assert default.keys == {}
    assert "resetpass" in default.raw


def test_every_user_starts_from_nothing() -> None:
    """Every grant on a line is one somebody wrote on purpose, never one
    inherited from a default that later widens."""
    for name, rules in _users().items():
        for reset in ("resetkeys", "resetchannels", "-@all"):
            assert reset in rules.raw, f"{name} does not start with {reset}"
        broad = {"allkeys", "allcommands", "~*", "+@all", "nopass", "allchannels"}
        assert not broad & set(rules.raw), f"{name} holds {broad & set(rules.raw)}"
        assert not any(c.startswith("+@") for c in rules.commands), (
            f"{name} is granted a whole command category; name the commands instead"
        )


def test_only_the_api_can_write_a_grant() -> None:
    for name, rules in _users().items():
        for pattern in GRANT_PATTERNS:
            if name == "api":
                assert rules.keys.get(pattern) == "RW", f"the API cannot write {pattern}"
            else:
                assert not _writes(rules, pattern), f"{name} can write {pattern}"


def test_the_worker_cannot_see_the_egress_keys_at_all() -> None:
    """A document that exploits a parser reaches the worker's Redis user.
    That user must hold nothing under `askwell:egress:`, read or write."""
    worker = _users()["worker"]
    assert not any(p.startswith("askwell:egress") for p in worker.keys), worker.keys
    assert worker.selectors == []


def test_the_api_reads_the_proxys_counters_and_cannot_forge_them() -> None:
    api = _users()["api"]
    for counter in (
        egress.REFUSED_COUNTER_KEY,
        egress.PERMITTED_COUNTER_KEY,
        egress.REFUSED_RECENT_KEY,
        egress.REPORTING_SINCE_KEY,
        egress.PERMITTED_BY_CONVERSATION_KEY,
    ):
        assert api.keys.get(counter) == "R", f"the API's access to {counter}"


def test_the_proxy_reads_grants_and_may_delete_only_conversation_grants() -> None:
    """The ticket's edge case: the proxy's startup DEL is still permitted,
    and nothing broader — DEL bound to that one prefix by a selector, and
    no DEL at all at the root."""
    proxy = _users()["proxy"]
    for pattern in GRANT_PATTERNS:
        assert proxy.keys.get(pattern) == "R", f"the proxy's access to {pattern}"
    assert "+del" not in proxy.commands
    assert len(proxy.selectors) == 1
    selector = proxy.selectors[0]
    assert selector.commands == {"+del"}
    assert selector.keys == {f"{egress.CONVERSATION_GRANT_KEY_PREFIX}*": "W"}


def test_the_health_check_can_only_ping() -> None:
    healthcheck = _users()["healthcheck"]
    assert healthcheck.commands == {"-@all", "+ping"}
    assert healthcheck.keys == {}


def test_every_password_placeholder_is_filled_by_the_start_script() -> None:
    placeholders = set(re.findall(r"@([A-Z_]+_SHA256)@", ACL.read_text(encoding="utf-8")))
    filled = set(re.findall(r"@([A-Z_]+_SHA256)@", START.read_text(encoding="utf-8")))
    assert (
        placeholders
        == filled
        == {
            "HEALTHCHECK_PASSWORD_SHA256",
            "API_PASSWORD_SHA256",
            "WORKER_PASSWORD_SHA256",
            "PROXY_PASSWORD_SHA256",
        }
    )
    # No password in plain text: the template carries hashes only (`#`), never
    # a `>password`, so a committed file cannot hold a credential (C8).
    assert not re.search(r"(^|\s)>", ACL.read_text(encoding="utf-8"))


# --- compose, read as text -----------------------------------------------------


def _environment_block(service: str) -> str:
    compose = COMPOSE.read_text(encoding="utf-8")
    body = compose.split(f"\n  {service}:\n", 1)[1]
    return re.split(r"\n  [a-z-]+:\n", body, maxsplit=1)[0]


@pytest.mark.parametrize(
    ("service", "user", "password"),
    [
        ("api", "api", "REDIS_API_PASSWORD"),
        ("worker", "worker", "REDIS_WORKER_PASSWORD"),
        ("egress-proxy", "proxy", "REDIS_PROXY_PASSWORD"),
    ],
)
def test_each_service_that_connects_is_its_own_user(service: str, user: str, password: str) -> None:
    block = _environment_block(service)
    assert f"ASKWELL_REDIS_USERNAME: {user}\n" in block
    # `:?` — Compose refuses to start without it; never a default.
    assert f"ASKWELL_REDIS_PASSWORD: ${{{password}:?" in block


@pytest.mark.parametrize("service", ["voice", "inference-bridge"])
def test_a_service_that_never_uses_redis_holds_no_credential(service: str) -> None:
    block = _environment_block(service)
    assert "ASKWELL_REDIS_" not in block


def test_redis_starts_from_the_acl_and_requires_every_password() -> None:
    block = _environment_block("redis")
    assert "--aclfile" in block
    assert "/askwell-redis/start.sh" in block
    for name in ("REDIS_API_PASSWORD", "REDIS_WORKER_PASSWORD", "REDIS_PROXY_PASSWORD"):
        assert f"{name}: ${{{name}:?" in block
    # The health check authenticates too; a bare `redis-cli ping` would now
    # be refused and report a healthy Redis as down.
    assert "--user healthcheck" in block


# --- a real Redis, refusing ----------------------------------------------------


def _require(name: str) -> str:
    """Deliberately not `pytest.skip` — the same rule as `conftest_db.py`."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"{name} is not set. These tests need the stack's own Redis — they "
            f"assert what it refuses. Run: scripts/dev.sh test-db"
        )
    return value


Connect = Callable[[str | None, str | None], redis.Redis]


@pytest.fixture
async def as_user() -> AsyncIterator[Connect]:
    host = os.environ.get("TEST_REDIS_HOST", "redis")
    port = int(os.environ.get("TEST_REDIS_PORT", "6379"))
    opened: list[redis.Redis] = []

    def connect(username: str | None, password: str | None) -> redis.Redis:
        client = redis.Redis(
            host=host,
            port=port,
            username=username,
            password=password,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
        )
        opened.append(client)
        return client

    yield connect
    for client in opened:
        await client.aclose()


def _password(user: str) -> str:
    return _require(f"TEST_REDIS_{user.upper()}_PASSWORD")


def _settings_as(user: str) -> Settings:
    return Settings(
        database_url="postgresql://askwell:pw@127.0.0.1:1/askwell",  # type: ignore[arg-type]
        sandbox_database_url="postgresql://x:x@127.0.0.1:1/postgres",  # type: ignore[arg-type]
        sandbox_owner_password="pw",  # type: ignore[arg-type]
        sandbox_readonly_password="pw",  # type: ignore[arg-type]
        redis_host=os.environ.get("TEST_REDIS_HOST", "redis"),
        redis_port=int(os.environ.get("TEST_REDIS_PORT", "6379")),
        redis_username=user,
        redis_password=SecretStr(_password(user)),
    )


@pytest.mark.requires_db
async def test_an_unauthenticated_connection_is_refused(as_user: Connect) -> None:
    """Also everything `voice` could do: it holds no credential at all."""
    client = as_user(None, None)
    with pytest.raises(AuthenticationError):
        await client.ping()
    with pytest.raises(AuthenticationError):
        await client.set(egress.PERMITTED_HOST_KEY, "attacker.example:443")


@pytest.mark.requires_db
async def test_a_wrong_password_is_refused(as_user: Connect) -> None:
    client = as_user("api", "not-the-password")
    with pytest.raises(AuthenticationError):
        await client.ping()


@pytest.mark.requires_db
@pytest.mark.parametrize(
    "key",
    [
        egress.PERMITTED_HOST_KEY,
        f"{egress.GRANT_KEY_PREFIX}test-{uuid.uuid4()}",
        f"{egress.CONVERSATION_GRANT_KEY_PREFIX}test-{uuid.uuid4()}",
    ],
)
async def test_the_worker_cannot_write_any_grant(as_user: Connect, key: str) -> None:
    """The ticket's real-world scenario: a malicious spreadsheet exploits a
    parsing bug in the worker and tries to set a permitted egress host."""
    worker = as_user("worker", _password("worker"))
    assert await worker.ping()
    with pytest.raises(NoPermissionError):
        await worker.set(key, "attacker.example:443")
    with pytest.raises(NoPermissionError):
        await worker.delete(key)
    with pytest.raises(NoPermissionError):
        await worker.get(key)


@pytest.mark.requires_db
async def test_the_worker_can_still_use_the_queue(as_user: Connect) -> None:
    worker = as_user("worker", _password("worker"))
    key = f"arq:job:askwell-test-{uuid.uuid4()}"
    assert await worker.set(key, "x", px=5000)
    assert await worker.get(key) == b"x"
    assert await worker.delete(key) == 1


@pytest.mark.requires_db
async def test_the_api_opens_a_grant_and_the_proxy_honours_it(as_user: Connect) -> None:
    """Web escalation's path end to end through the real code: the API
    writes the turn grant, the proxy reads it, the API closes it."""
    turn = f"test-{uuid.uuid4()}"
    destination = f"{turn}.invalid:443"
    api, proxy_settings = _settings_as("api"), _settings_as("proxy")
    proxy = egress.EgressProxy(proxy_settings)

    assert await egress.open_grant(
        api, turn_id=turn, destination=destination, accepted=True, ttl_seconds=5
    )
    try:
        assert await proxy._grant_permits(destination)
    finally:
        await egress.close_grant(api, turn)
    assert not await proxy._grant_permits(destination)


@pytest.mark.requires_db
async def test_the_proxy_cannot_write_a_grant(as_user: Connect) -> None:
    proxy = as_user("proxy", _password("proxy"))
    for key in (
        egress.PERMITTED_HOST_KEY,
        f"{egress.GRANT_KEY_PREFIX}test-{uuid.uuid4()}",
        f"{egress.CONVERSATION_GRANT_KEY_PREFIX}test-{uuid.uuid4()}",
    ):
        with pytest.raises(NoPermissionError):
            await proxy.set(key, "attacker.example:443")


@pytest.mark.requires_db
async def test_the_proxy_may_delete_a_conversation_grant_and_nothing_else(
    as_user: Connect,
) -> None:
    """Its startup revocation, and no broader DEL."""
    api = as_user("api", _password("api"))
    proxy = as_user("proxy", _password("proxy"))
    conversation = f"{egress.CONVERSATION_GRANT_KEY_PREFIX}test-{uuid.uuid4()}"
    turn = f"{egress.GRANT_KEY_PREFIX}test-{uuid.uuid4()}"
    await api.set(conversation, '{"destination": "x.invalid:443", "token_sha256": "0"}', ex=5)
    await api.set(turn, "x.invalid:443", ex=5)
    try:
        assert await proxy.delete(conversation) == 1
        for key in (turn, egress.PERMITTED_HOST_KEY, egress.REFUSED_COUNTER_KEY):
            with pytest.raises(NoPermissionError):
                await proxy.delete(key)
        # DEL is the one write; GETDEL, UNLINK and the like are not DEL.
        with pytest.raises(NoPermissionError):
            await proxy.unlink(turn)
    finally:
        await api.delete(conversation, turn)


@pytest.mark.requires_db
async def test_the_proxy_records_its_counters_and_the_api_cannot(as_user: Connect) -> None:
    """The refusal count is the proxy's own measurement; the API reads it
    and cannot inflate or zero it."""
    proxy = as_user("proxy", _password("proxy"))
    api = as_user("api", _password("api"))
    assert await proxy.incr(egress.REFUSED_COUNTER_KEY, 0) is not None
    assert await api.get(egress.REFUSED_COUNTER_KEY) is not None
    with pytest.raises(NoPermissionError):
        await api.set(egress.REFUSED_COUNTER_KEY, 0)
    with pytest.raises(NoPermissionError):
        await api.incr(egress.REFUSED_COUNTER_KEY)
