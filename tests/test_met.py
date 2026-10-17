"""MET connector with a fake HTTP session (no network) and a recorded response."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests

from northlink import store
from northlink.connectors import met

FIX = Path(__file__).parent / "fixtures" / "met_example_2026-10-15.json"
URL = met.build_url("current", "55")
NOW = datetime(2026, 10, 15, 17, 0, tzinfo=timezone.utc)


class Resp:
    def __init__(self, status, body=b"", headers=None):
        self.status_code, self.content, self.headers = status, body, headers or {}


class Session:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def get(self, url, headers=None, timeout=None):
        self.calls.append((url, headers, timeout))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def H(exp_min=3):
    return {"Last-Modified": "Thu, 15 Oct 2026 16:59:00 GMT",
            "Expires": (NOW + timedelta(minutes=exp_min)).strftime("%a, %d %b %Y %H:%M:%S GMT")}


def test_url_and_parse_recorded_example():
    assert URL.startswith("https://api.met.no/weatherapi/metalerts/2.0/current.json?") and "county=55" in URL
    import json
    alerts = met.parse_alerts(json.loads(FIX.read_bytes()))
    assert alerts and all(a.status == "Test" for a in alerts)  # example endpoint is labelled Test
    assert alerts[0].onset and alerts[0].bbox and alerts[0].cap_uri


@pytest.fixture(autouse=True)
def ua(monkeypatch):
    monkeypatch.setenv(met.UA_VAR, "northlink-test/0.1 (team contact: test@example.org)")


def test_fetch_saves_raw_and_respects_cache_and_failures(tmp_path):
    conn = store.connect(tmp_path / "m.db")
    body = FIX.read_bytes()
    s = Session(Resp(200, body, H()), requests.ConnectionError("offline"), Resp(304, b"", H()))
    r = met.refresh(conn, URL, session=s, now=NOW, cache_dir=tmp_path / "c")
    assert r.ok and len(s.calls) == 1
    ua = s.calls[0][1]["User-Agent"]
    assert ua == "northlink-test/0.1 (team contact: test@example.org)" and s.calls[0][2] is not None
    data, row = met.load_cached(conn, URL)
    assert Path(row["raw_path"]).read_bytes() == body  # original bytes preserved

    # Before Expires: no network call.
    assert met.refresh(conn, URL, session=s, now=NOW + timedelta(minutes=1), cache_dir=tmp_path / "c").from_cache
    assert len(s.calls) == 1

    # After Expires, offline: failure recorded, last success kept.
    r = met.refresh(conn, URL, session=s, now=NOW + timedelta(minutes=10), cache_dir=tmp_path / "c")
    assert not r.ok
    assert met.last_success(conn, URL)["attempted_at"] == "2026-10-15T17:00:00Z"
    assert met.last_attempt(conn, URL)["successful"] == 0
    assert met.load_cached(conn, URL)[0] == data

    # 304 with If-Modified-Since: successful check, same body.
    r = met.refresh(conn, URL, session=s, now=NOW + timedelta(minutes=20), cache_dir=tmp_path / "c")
    assert r.ok and "If-Modified-Since" in s.calls[-1][1]
    assert met.last_success(conn, URL)["not_modified"] == 1
    assert met.load_cached(conn, URL)[0] == data


def test_http_error_and_bad_body_do_not_raise(tmp_path):
    conn = store.connect(tmp_path / "m.db")
    s = Session(Resp(403, b"forbidden"), Resp(200, b"<html>", {}))
    assert "User-Agent" in met.refresh(conn, URL, session=s, now=NOW, cache_dir=tmp_path).message
    assert not met.refresh(conn, URL, session=s, now=NOW, cache_dir=tmp_path).ok
    assert met.last_success(conn, URL) is None


def test_user_agent_from_dotenv_reaches_request(tmp_path, monkeypatch):
    monkeypatch.delenv(met.UA_VAR, raising=False)
    env = tmp_path / ".env"
    env.write_text(f"{met.UA_VAR}=northlink-dotenv/0.1 (contact: team@example.org)\n")
    monkeypatch.setattr(met, "ENV_FILE", env)
    monkeypatch.setattr(met.user_agent, "__defaults__", (env,))
    conn = store.connect(tmp_path / "m.db")
    s = Session(Resp(200, FIX.read_bytes(), H()))
    assert met.refresh(conn, URL, session=s, now=NOW, cache_dir=tmp_path / "c").ok
    assert s.calls[0][1]["User-Agent"] == "northlink-dotenv/0.1 (contact: team@example.org)"


def test_no_user_agent_means_no_request(tmp_path, monkeypatch):
    monkeypatch.delenv(met.UA_VAR, raising=False)
    monkeypatch.setattr(met.user_agent, "__defaults__", (tmp_path / "missing.env",))
    conn = store.connect(tmp_path / "m.db")
    s = Session()
    r = met.refresh(conn, URL, session=s, now=NOW, cache_dir=tmp_path)
    assert not r.ok and met.UA_VAR in r.message and s.calls == []
