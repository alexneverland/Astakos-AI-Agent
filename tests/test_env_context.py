import pytest
import time
import json
import os
import tempfile
import clients.telegram_bot as bot
from clients.telegram_bot import _get_env_context

@pytest.fixture(autouse=True)
def setup_teardown_cache(monkeypatch):
    # Reset cache before every test
    bot._ENV_CONTEXT_CACHE = {"ts": 0.0, "value": "", "gps_key": None}
    
    # Mock config locations in the config module since they are imported locally
    import config
    import clients.telegram_bot as bot_module
    
    monkeypatch.setattr(config, "HOME_COORDS", (40.0, 22.0))
    monkeypatch.setattr(config, "HOME_RADIUS_M", 150)
    monkeypatch.setattr(config, "WORK_COORDS", (41.0, 23.0))
    monkeypatch.setattr(config, "WORK_RADIUS_M", 300)
    
    # Use a temporary file for GPS storage
    fd, fake_gps_file = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    monkeypatch.setattr(config, "GPS_STORAGE_FILE", fake_gps_file)
    yield fake_gps_file
    
    try:
        os.remove(fake_gps_file)
    except:
        pass
    
def mock_requests_get(url, **kwargs):
    class MockResponse:
        def json(self):
            return {
                "current": {
                    "temperature_2m": 25.0,
                    "precipitation": 0.0,
                    "weather_code": 0
                }
            }
    return MockResponse()

def mock_requests_get_fail(url, **kwargs):
    raise Exception("API down")

def test_recent_home_coords(monkeypatch, setup_teardown_cache):
    monkeypatch.setattr("requests.get", mock_requests_get)
    fake_gps_file = setup_teardown_cache
    
    with open(fake_gps_file, "w", encoding="utf-8") as f:
        json.dump({"lat": 40.0001, "lon": 22.0001, "timestamp": time.time()}, f)
        
    result = _get_env_context()
    assert "[USER ENVIRONMENTAL DATA]" in result
    assert "ΣΤΟ ΣΠΙΤΙ" in result
    assert "25.0°C" in result

def test_recent_work_coords(monkeypatch, setup_teardown_cache):
    monkeypatch.setattr("requests.get", mock_requests_get)
    fake_gps_file = setup_teardown_cache
    
    with open(fake_gps_file, "w", encoding="utf-8") as f:
        json.dump({"lat": 41.0001, "lon": 23.0001, "timestamp": time.time()}, f)
        
    result = _get_env_context()
    assert "[USER ENVIRONMENTAL DATA]" in result
    assert "ΣΤΗ ΔΟΥΛΕΙΑ" in result

def test_stale_timestamp(monkeypatch, setup_teardown_cache):
    fake_gps_file = setup_teardown_cache
    
    with open(fake_gps_file, "w", encoding="utf-8") as f:
        json.dump({"lat": 40.0, "lon": 22.0, "timestamp": time.time() - 20000}, f)
        
    result = _get_env_context()
    assert result == ""
    assert bot._ENV_CONTEXT_CACHE["value"] == ""
    assert bot._ENV_CONTEXT_CACHE["gps_key"] is None

def test_weather_fail_fallback(monkeypatch, setup_teardown_cache):
    monkeypatch.setattr("requests.get", mock_requests_get_fail)
    fake_gps_file = setup_teardown_cache
    
    with open(fake_gps_file, "w", encoding="utf-8") as f:
        json.dump({"lat": 45.0, "lon": 25.0, "timestamp": time.time()}, f)
        
    result = _get_env_context()
    assert "[USER ENVIRONMENTAL DATA]" in result
    assert "Location:" in result
    assert "ΕΚΤΟΣ ΣΠΙΤΙΟΥ" in result
    assert "25.0°C" not in result
