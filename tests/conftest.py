"""Shared fixtures: a live server bound to a throwaway MATHMUSIC_HOME."""

import json
import threading
import urllib.error
import urllib.request

import pytest


@pytest.fixture
def api(tmp_path, monkeypatch):
    from mathmusic.server import make_server

    monkeypatch.setenv("MATHMUSIC_HOME", str(tmp_path))
    server = make_server(0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def call(path, method="GET", body=None, headers=None):
        data = None if body is None else json.dumps(body).encode()
        hdrs = {"Content-Type": "application/json"} if body is not None else {}
        hdrs.update(headers or {})
        req = urllib.request.Request(base + path, method=method, data=data, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                raw = res.read()
                return res.status, (json.loads(raw) if res.headers.get_content_type() == "application/json" else raw)
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                return exc.code, json.loads(raw)
            except ValueError:
                return exc.code, raw

    call.base = base
    call.server = server
    yield call
    server.shutdown()
    server.server_close()
