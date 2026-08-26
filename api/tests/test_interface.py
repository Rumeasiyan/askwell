"""Serving the built interface.

The two requirements that pull against each other get most of the attention
here: a bookmarked deep route must load, and a typo must not silently return
a working-looking shell that is not the page anyone asked for.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from askwell.app import create_app
from askwell.config import Settings


@pytest.fixture
def built(tmp_path: Path) -> Path:
    """A minimal static export: an index, a route directory, a hashed asset."""
    (tmp_path / "index.html").write_text("<!doctype html><title>Askwell</title>root")
    (tmp_path / "404.html").write_text("<!doctype html><title>Not found</title>missing")

    library = tmp_path / "library"
    library.mkdir()
    (library / "index.html").write_text("<!doctype html><title>Library</title>library route")

    hashed = tmp_path / "_next" / "static" / "chunks"
    hashed.mkdir(parents=True)
    (hashed / "abc123.js").write_text("console.log(1)")

    (tmp_path / "favicon.ico").write_bytes(b"\x00")
    return tmp_path


@pytest.fixture
def client(settings: Settings, built: Path) -> TestClient:
    return TestClient(create_app(settings.model_copy(update={"web_assets_dir": built})))


def test_the_root_serves_the_interface(client: TestClient) -> None:
    with client:
        response = client.get("/")
    assert response.status_code == 200
    assert "Askwell" in response.text


def test_a_deep_route_loads_directly(client: TestClient) -> None:
    """Someone bookmarks the library and opens it the next morning."""
    with client:
        response = client.get("/library/")
    assert response.status_code == 200
    assert "library route" in response.text


def test_a_deep_route_loads_without_the_trailing_slash(client: TestClient) -> None:
    with client:
        response = client.get("/library")
    assert response.status_code == 200
    assert "library route" in response.text


def test_an_unknown_path_is_not_the_application_shell(client: TestClient) -> None:
    """The failure this guards against looks like success.

    Returning index.html for anything unmatched makes deep routes work and
    turns every typo into a working-looking interface that is not the page the
    user asked for, with nothing to indicate it went wrong.
    """
    with client:
        shell = client.get("/")
        response = client.get("/libary/", headers={"accept": "text/html"})

    assert response.status_code == 404
    # Compared against the shell's own body rather than against a title or a
    # marker string. The real export gives every page the same <title>, so a
    # title check would pass here and still miss the defect in production.
    assert response.text != shell.text


def test_an_unknown_path_gets_the_products_own_404_page(client: TestClient) -> None:
    with client:
        response = client.get("/nope/", headers={"accept": "text/html"})
    assert response.status_code == 404
    assert "missing" in response.text


def test_a_non_browser_client_gets_a_readable_error(client: TestClient) -> None:
    with client:
        response = client.get("/nope", headers={"accept": "application/json"})
    assert response.status_code == 404
    assert response.json()["path"] == "nope"


def test_api_routes_are_not_shadowed_by_the_catch_all(client: TestClient) -> None:
    """The catch-all matches everything. Registration order is what saves /health."""
    with client:
        response = client.get("/health")
    assert response.status_code == 200
    assert "components" in response.json()


@pytest.mark.parametrize(
    "attack",
    [
        "../../../../etc/passwd",
        "..%2f..%2f..%2fetc%2fpasswd",
        "library/../../../etc/passwd",
        "/etc/passwd",
        "....//....//etc/passwd",
    ],
)
def test_no_path_escapes_the_asset_directory(client: TestClient, attack: str) -> None:
    with client:
        response = client.get(f"/{attack}")
    assert response.status_code == 404
    assert "root:" not in response.text


def test_a_symlink_out_of_the_directory_is_refused(client: TestClient, built: Path) -> None:
    """resolve() collapses the symlink, so containment is checked on the real path."""
    outside = built.parent / "secret.txt"
    outside.write_text("not for serving")
    (built / "escape.txt").symlink_to(outside)

    with client:
        response = client.get("/escape.txt")
    assert response.status_code == 404
    assert "not for serving" not in response.text


def test_hashed_assets_are_cached_immutably(client: TestClient) -> None:
    with client:
        response = client.get("/_next/static/chunks/abc123.js")
    assert response.status_code == 200
    assert "immutable" in response.headers["cache-control"]


def test_html_is_revalidated_so_a_rebuild_is_not_missed(client: TestClient) -> None:
    """The HTML is what points at the new hashed filenames.

    Cache it like the assets and a rebuild leaves the user on the old bundle
    until they clear their cache by hand — with no reason to suspect that is
    what happened.
    """
    with client:
        for path in ("/", "/library/"):
            response = client.get(path)
            assert response.headers["cache-control"] == "no-cache", path


def test_a_rebuild_is_served_rather_than_the_old_bundle(client: TestClient, built: Path) -> None:
    with client:
        first = client.get("/")
        assert "root" in first.text

        (built / "index.html").write_text("<!doctype html><title>Askwell</title>rebuilt")
        second = client.get("/")

    assert "rebuilt" in second.text


def test_other_assets_get_a_short_revalidating_cache(client: TestClient) -> None:
    with client:
        response = client.get("/favicon.ico")
    assert "must-revalidate" in response.headers["cache-control"]


def test_a_missing_build_says_so_rather_than_showing_a_blank_page(
    settings: Settings, tmp_path: Path
) -> None:
    """A contributor who has not built the frontend, or a broken install."""
    empty = tmp_path / "never-built"
    empty.mkdir()
    app = create_app(settings.model_copy(update={"web_assets_dir": empty}))

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 503
    assert "has not been built" in response.text
    assert "scripts/dev.sh web-build" in response.text
    assert str(empty) in response.text
    # Non-empty, and readable without a developer console.
    assert len(response.text) > 400


def test_health_still_works_when_the_interface_is_missing(
    settings: Settings, tmp_path: Path
) -> None:
    """Whoever has no interface needs the health surface more than anyone."""
    app = create_app(settings.model_copy(update={"web_assets_dir": tmp_path / "nothing"}))
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert len(response.json()["components"]) == 5
