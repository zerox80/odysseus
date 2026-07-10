import json

import routes.embedding_routes as embedding_routes


def test_load_custom_endpoint_ignores_non_object_json(tmp_path, monkeypatch):
    endpoint_file = tmp_path / "embedding_endpoint.json"
    endpoint_file.write_text(json.dumps(["not", "an", "endpoint", "object"]), encoding="utf-8")
    monkeypatch.setattr(embedding_routes, "_ENDPOINT_FILE", str(endpoint_file))

    assert embedding_routes._load_custom_endpoint() == {}


def test_load_custom_endpoint_keeps_object_json(tmp_path, monkeypatch):
    endpoint_file = tmp_path / "embedding_endpoint.json"
    endpoint_file.write_text(
        json.dumps({"url": "http://127.0.0.1:11434", "model": "nomic-embed-text"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(embedding_routes, "_ENDPOINT_FILE", str(endpoint_file))

    assert embedding_routes._load_custom_endpoint() == {
        "url": "http://127.0.0.1:11434",
        "model": "nomic-embed-text",
    }


def test_save_custom_endpoint_uses_atomic_json_write(monkeypatch):
    saved = {}

    def _atomic_write_json(path, data, *, indent=None):
        saved.update(path=path, data=data, indent=indent)

    monkeypatch.setattr(embedding_routes, "atomic_write_json", _atomic_write_json)
    monkeypatch.setattr(embedding_routes, "_ENDPOINT_FILE", "test-endpoint.json")

    embedding_routes._save_custom_endpoint({"url": "http://localhost:11434"})

    assert saved == {
        "path": "test-endpoint.json",
        "data": {"url": "http://localhost:11434"},
        "indent": 2,
    }
