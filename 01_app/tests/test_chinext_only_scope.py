"""Current live scope: only the ChiNext knowledge boundary is available."""
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app
from conftest import KNOWLEDGE, isolated_root
from backend.boards import ACTIVE_BOARDS


ROOT = Path(__file__).resolve().parents[1]


def test_api_and_filesystem_expose_only_chinext(tmp_path):
    app = create_app(tmp_path / "var", isolated_root(tmp_path), {"allowed_hosts": ["testserver"]})
    with TestClient(app) as client:
        metadata = client.get("/api/meta").json()
        assert ACTIVE_BOARDS == {"chinext"}
        assert [row["id"] for row in metadata["boards"] if row["available"]] == ["chinext"]
        assert {row["layer"] for row in metadata["companies"]} == {"chinext"}
        assert client.get("/api/meta", params={"board": "base"}).status_code == 409
        assert client.get("/api/meta", params={"board": "innovation"}).status_code == 409
        assert client.get("/api/library/search", params={"board": "base"}).status_code == 409
        assert client.get("/api/library/search", params={"board": "chinext", "collection": "blacklist_cases"}).json()["total"] == 5

    assert not (KNOWLEDGE / "data/public/boards/base").exists()
    assert not (KNOWLEDGE / "data/public/boards/innovation").exists()
    assert (KNOWLEDGE / "data/public/boards/chinext/catalog.json").is_file()
