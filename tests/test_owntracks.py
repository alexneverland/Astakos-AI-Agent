"""Offline OwnTracks intake, abuse cases and persisted location integration."""
import hashlib
import base64
import asyncio
import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def intake(tmp_path, monkeypatch):
    """Mount the real intake with private temporary credentials and queue."""
    from api.owntracks import build_owntracks_app
    from services.owntracks import OwnTracksStore

    password = "a" * 64
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(json.dumps({"username": "owner", "device": "phone",
        "secret_sha256": hashlib.sha256(password.encode()).hexdigest()}))
    store = OwnTracksStore(tmp_path / "queue.json")
    app = FastAPI()
    app.mount("/owntracks", build_owntracks_app(auth_file=auth_file, store=store))
    client = TestClient(app)
    client.headers["X-Limit-D"] = "phone"
    return client, store, auth_file, ("owner", password)


def point(**changes):
    """Return a realistic actual fix, unrelated metadata must not be retained."""
    return {"_type": "location", "lat": 40.0, "lon": 22.0,
            "tst": int(time.time()) - 1, "acc": 20, "SSID": "private", **changes}


@pytest.mark.parametrize("partial", [b"", b'{"_type":"location",'])
def test_disconnected_upload_is_rejected_without_intake_and_next_fix_recovers(intake, partial):
    """Exercise real ASGI disconnect events without accepting a partial report."""
    client, store, _, auth = intake
    token = base64.b64encode(":".join(auth).encode())
    events = iter([{"type": "http.request", "body": partial, "more_body": True},
                   {"type": "http.disconnect"}])
    responses = []

    async def receive():
        return next(events)

    async def send(message):
        responses.append(message)

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
             "method": "POST", "scheme": "http", "path": "/owntracks/",
             "raw_path": b"/owntracks/", "query_string": b"", "root_path": "",
             "headers": [(b"authorization", b"Basic " + token), (b"x-limit-d", b"phone")],
             "client": ("127.0.0.1", 1234), "server": ("testserver", 80)}
    asyncio.run(client.app(scope, receive, send))
    assert responses[0]["status"] == 400
    assert not store.pending()
    assert not store.path.exists()
    assert client.post("/owntracks/", json=point(), auth=auth).status_code == 200
    assert len(store.pending()) == 1


def test_auth_is_mandatory_even_for_local_proxy(intake):
    client, store, _, auth = intake
    for credentials in (None, ("owner", "wrong"), ("other", auth[1])):
        assert client.post("/owntracks/", json=point(), auth=credentials).status_code == 401
    assert not store.pending()


def test_device_and_disabled_configuration_fail_closed(intake):
    client, store, auth_file, auth = intake
    client.headers["X-Limit-D"] = "other"
    assert client.post("/owntracks/", json=point(), auth=auth).status_code == 403
    client.headers["X-Limit-D"] = "phone"
    auth_file.unlink()
    assert client.post("/owntracks/", json=point(), auth=auth).status_code == 503
    assert not store.pending()


def test_accepted_fix_is_durable_minimal_and_deduplicated(intake):
    client, store, _, auth = intake
    payload = point()
    for _ in range(2):
        response = client.post("/owntracks/", json=payload, auth=auth)
        assert response.status_code == 200 and response.json() == []
    from services.owntracks import OwnTracksStore
    rows = OwnTracksStore(store.path).pending()
    assert rows == [{k: payload[k] for k in ("lat", "lon", "tst", "acc")}]
    assert "private" not in store.path.read_text()


@pytest.mark.parametrize("changes", [
    {"tst": int(time.time()) - 601}, {"tst": int(time.time()) + 120},
    {"acc": 101}, {"t": "p"}, {"_type": "transition"},
])
def test_unusable_reports_acknowledged_without_refreshing_location(intake, changes):
    client, store, _, auth = intake
    assert client.post("/owntracks/", json=point(**changes), auth=auth).status_code == 200
    assert not store.pending()


@pytest.mark.parametrize("changes", [
    {"lat": True}, {"lon": "22"}, {"lat": 91}, {"lon": float("inf")},
    {"tst": True}, {"tst": "123"}, {"acc": -1}, {"acc": None},
])
def test_malformed_fix_rejected_without_writes(intake, changes):
    client, store, _, auth = intake
    response = client.post("/owntracks/", content=json.dumps(point(**changes)),
                           auth=auth, headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert not store.pending()


def test_body_limit_and_mount_do_not_expose_other_api_routes(intake):
    client, store, _, auth = intake
    assert client.post("/owntracks/", content="x" * 9000, auth=auth).status_code == 413
    assert client.get("/owntracks/debug/runtime", auth=auth).status_code == 404
    assert client.get("/owntracks/docs", auth=auth).status_code == 404
    assert not store.pending()


def test_queue_is_bounded_and_old_source_time_cannot_replace_latest(tmp_path):
    from services.owntracks import OwnTracksStore
    store = OwnTracksStore(tmp_path / "queue.json")
    for i in range(101):
        store.enqueue(point(tst=i + 1))
    assert len(store.pending()) == 100
    assert not store.enqueue(point(tst=50))
    assert store.pending()[-1]["tst"] == 101


def test_drain_uses_real_pipeline_and_temporary_reminder_store(intake, tmp_path, monkeypatch):
    import config
    from services.owntracks import drain_owntracks
    from tests.test_reminders_sql import _make_reminders_db, _row_status
    from services import location_update

    client, store, _, auth = intake
    db = tmp_path / "state.db"
    _make_reminders_db(str(db), [{"task": "meat", "time": "loc:home"}])
    monkeypatch.setattr(config, "STATE_DB", str(db))
    monkeypatch.setattr(config, "GPS_STORAGE_FILE", str(tmp_path / "location.json"))
    monkeypatch.setattr(config, "HOME_COORDS", (40.0, 22.0))
    monkeypatch.setattr(config, "HOME_RADIUS_M", 150)
    flags = []
    monkeypatch.setattr(location_update, "sync_live_location_out_of_home_state",
                        lambda lat, lon: flags.append((lat, lon)))
    payload = point()
    assert client.post("/owntracks/", json=payload, auth=auth).status_code == 200
    sent = []
    drain_owntracks(store=store, channel="matrix", send_reminder=sent.append)
    drain_owntracks(store=store, channel="matrix", send_reminder=sent.append)
    saved = json.loads((tmp_path / "location.json").read_text())
    assert saved["timestamp"] == payload["tst"]
    assert _row_status(str(db), "meat") == "done"
    assert len(sent) == 1 and flags == [(40.0, 22.0)]
    assert not store.pending()


def test_worker_rechecks_age_and_cross_channel_order(intake, tmp_path, monkeypatch):
    import config
    from services.owntracks import drain_owntracks
    client, store, _, auth = intake
    location = tmp_path / "location.json"
    monkeypatch.setattr(config, "GPS_STORAGE_FILE", str(location))
    payload = point()
    assert client.post("/owntracks/", json=payload, auth=auth).status_code == 200
    location.write_text(json.dumps({"lat": 1, "lon": 2, "timestamp": payload["tst"] + 1}))
    before = location.read_bytes()
    drain_owntracks(store=store, channel="matrix", send_reminder=lambda _: pytest.fail("outbound"))
    assert location.read_bytes() == before
    store.enqueue(point(tst=payload["tst"] + 2))
    drain_owntracks(store=store, channel="matrix", now_ts=payload["tst"] + 1000,
                   send_reminder=lambda _: pytest.fail("outbound"))
    assert location.read_bytes() == before and not store.pending()


def test_failed_delivery_keeps_reminder_pending_for_next_actual_fix(intake, tmp_path, monkeypatch):
    import config
    from services.owntracks import drain_owntracks
    from tests.test_reminders_sql import _make_reminders_db, _row_status
    from services import location_update
    client, store, _, auth = intake
    db = tmp_path / "state.db"
    _make_reminders_db(str(db), [{"task": "meat", "time": "loc:home"}])
    monkeypatch.setattr(config, "STATE_DB", str(db))
    monkeypatch.setattr(config, "GPS_STORAGE_FILE", str(tmp_path / "location.json"))
    monkeypatch.setattr(config, "HOME_COORDS", (40.0, 22.0))
    monkeypatch.setattr(config, "HOME_RADIUS_M", 150)
    monkeypatch.setattr(location_update, "sync_live_location_out_of_home_state", lambda *_: None)
    payload = point(tst=int(time.time()) - 5)
    client.post("/owntracks/", json=payload, auth=auth)
    def offline(_):
        raise RuntimeError("transport unavailable")
    drain_owntracks(store=store, channel="matrix", send_reminder=offline)
    assert _row_status(str(db), "meat") == "pending"
    client.post("/owntracks/", json=point(tst=payload["tst"] + 1), auth=auth)
    sent = []
    drain_owntracks(store=store, channel="matrix", send_reminder=sent.append)
    assert len(sent) == 1 and _row_status(str(db), "meat") == "done"


def test_private_provisioning_export_authenticates_without_printing_secret(tmp_path, capsys):
    from scripts.configure_owntracks import provision
    from api.owntracks import build_owntracks_app
    from services.owntracks import OwnTracksStore
    export = provision(tmp_path, "https://example.tailnet.ts.net/owntracks/")
    settings = json.loads(export.read_text())
    assert capsys.readouterr().out == ""
    assert settings["mode"] == 3 and settings["ping"] == 0
    assert settings["locatorDisplacement"] == 0 and settings["locatorInterval"] == 120
    auth = tmp_path / "credentials" / "owntracks-auth.json"
    assert settings["password"] not in auth.read_text()
    client = TestClient(build_owntracks_app(auth_file=auth, store=OwnTracksStore(tmp_path / "queue.json")))
    assert client.post("/", json=point(), auth=(settings["username"], settings["password"]),
        headers={"X-Limit-D": settings["deviceId"]}).status_code == 200
    before = auth.read_bytes()
    with pytest.raises(FileExistsError):
        provision(tmp_path, settings["url"])
    assert auth.read_bytes() == before


@pytest.mark.parametrize("url", ["http://example/owntracks/", "https://user:pass@example/owntracks/",
    "https://example/owntracks/?secret=1", "https://example/", "https://example/owntracks/#x"])
def test_provisioning_rejects_insecure_or_wrong_endpoint(tmp_path, url):
    from scripts.configure_owntracks import provision
    with pytest.raises(ValueError):
        provision(tmp_path, url)
    assert not (tmp_path / "credentials").exists()


def test_real_owner_context_does_not_change_family_or_work(intake, tmp_path, monkeypatch):
    import config
    from memory import routine_db
    from services.owntracks import drain_owntracks
    from tests.test_reminders_sql import _make_reminders_db
    monkeypatch.setattr(routine_db, "DB_PATH", str(tmp_path / "routines.db"))
    routine_db.setup_db()
    for key in ("partner_with_user", "kid1_with_user", "user_at_work"):
        routine_db.set_context_state(key, "true")
    db = tmp_path / "state.db"
    _make_reminders_db(str(db), [])
    monkeypatch.setattr(config, "STATE_DB", str(db))
    monkeypatch.setattr(config, "GPS_STORAGE_FILE", str(tmp_path / "location.json"))
    monkeypatch.setattr(config, "HOME_COORDS", (40.0, 22.0))
    monkeypatch.setattr(config, "HOME_RADIUS_M", 150)
    before = {key: routine_db.get_context_state(key) for key in
              ("partner_with_user", "kid1_with_user", "user_at_work")}
    client, store, _, auth = intake
    client.post("/owntracks/", json=point(lat=40.01), auth=auth)
    drain_owntracks(store=store, channel="matrix", send_reminder=lambda _: pytest.fail("outbound"))
    assert routine_db.get_context_state("user_out_of_home")["value"] == "true"
    assert before == {key: routine_db.get_context_state(key) for key in before}


def test_concurrent_retries_admit_only_one_point(intake):
    from concurrent.futures import ThreadPoolExecutor
    client, store, _, auth = intake
    payload = point()
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: client.post("/owntracks/", json=payload, auth=auth), range(8)))
    assert all(response.status_code == 200 for response in responses)
    assert len(store.pending()) == 1


def test_durable_write_failure_returns_retryable_status(intake, monkeypatch):
    from services import owntracks
    client, store, _, auth = intake
    def fail(*_):
        raise OSError("private storage detail")
    monkeypatch.setattr(owntracks, "write_private_json", fail)
    response = client.post("/owntracks/", json=point(), auth=auth)
    assert response.status_code == 503
    assert "private storage detail" not in response.text
    assert not store.pending()


def test_partial_provisioning_recovers_same_phone_credential(tmp_path, monkeypatch):
    """Verifier write failure or interrupted setup must not strand the import."""
    from scripts import configure_owntracks as provisioning
    from api.owntracks import build_owntracks_app
    from services.owntracks import OwnTracksStore
    original = provisioning.write_private_json
    def fail_verifier(path, value):
        if path.name == "owntracks-auth.json":
            raise OSError("simulated failure")
        original(path, value)
    monkeypatch.setattr(provisioning, "write_private_json", fail_verifier)
    url = "https://example.tailnet.ts.net/owntracks/"
    with pytest.raises(OSError):
        provisioning.provision(tmp_path, url)
    export = tmp_path / "credentials" / "owntracks.otrc"
    before = export.read_bytes()
    settings = json.loads(before)
    monkeypatch.setattr(provisioning, "write_private_json", original)
    assert provisioning.provision(tmp_path, url) == export
    assert export.read_bytes() == before
    client = TestClient(build_owntracks_app(
        auth_file=export.with_name("owntracks-auth.json"),
        store=OwnTracksStore(tmp_path / "queue.json")))
    assert client.post("/", json=point(), auth=(settings["username"], settings["password"]),
        headers={"X-Limit-D": settings["deviceId"]}).status_code == 200


@pytest.mark.parametrize("change", [{"password": "weak"}, {"url": "https://other/owntracks/"},
    {"_type": "location"}, {"deviceId": "other"}])
def test_partial_provisioning_refuses_invalid_export_without_overwrite(tmp_path, change):
    """Recovery accepts only the generated credential for the requested endpoint."""
    from scripts.configure_owntracks import provision
    url = "https://example.tailnet.ts.net/owntracks/"
    export = provision(tmp_path, url)
    auth = export.with_name("owntracks-auth.json")
    auth.unlink()
    data = json.loads(export.read_text())
    data.update(change)
    export.write_text(json.dumps(data))
    before = export.read_bytes()
    with pytest.raises(ValueError):
        provision(tmp_path, url)
    assert export.read_bytes() == before and not auth.exists()
