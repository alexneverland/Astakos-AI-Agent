# ================================================================
# Project: Astakos AI Agent 🦞
# Description: Test suite for Jarvis-style Web UI Companion Interface
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

INDEX_HTML_PATH = Path(__file__).resolve().parent.parent / "index.html"


@pytest.fixture
def index_html_content() -> str:
    """Read the index.html file content."""
    assert INDEX_HTML_PATH.is_file(), f"index.html not found at {INDEX_HTML_PATH}"
    return INDEX_HTML_PATH.read_text(encoding="utf-8")


def test_index_html_file_exists(index_html_content: str) -> None:
    """index.html must exist and contain basic HTML5 document structure."""
    assert "<!DOCTYPE html>" in index_html_content
    assert "<html lang=\"el\">" in index_html_content
    assert "Astakos — AI Companion" in index_html_content


def test_astakos_core_svg_and_orbital_structure(index_html_content: str) -> None:
    """Astakos Core must feature circular SVG with orbital rings, particles, and nucleus."""
    assert "id=\"astakos-core-svg\"" in index_html_content
    assert "class=\"state-idle\"" in index_html_content
    # Orbital rings
    assert "core-orbit-outer" in index_html_content
    assert "core-orbit-middle" in index_html_content
    assert "core-orbit-inner" in index_html_content
    # Particles and Nucleus
    assert "core-particles-outer" in index_html_content
    assert "core-particles-middle" in index_html_content
    assert "core-nucleus" in index_html_content
    # Waveform for speaking
    assert "core-waveform" in index_html_content


def test_companion_hud_keeps_the_core_as_the_visual_anchor(index_html_content: str) -> None:
    """The desktop HUD centers the Core while retaining a compact mobile layout."""
    assert "justify-content: center;" in index_html_content
    assert "min-height: 148px;" in index_html_content
    assert "#companion-hud::before" in index_html_content
    assert "#core-hint" in index_html_content
    assert "Click core to speak" in index_html_content
    assert "#core-orb-wrapper { width: 82px; height: 82px; }" in index_html_content


def test_astakos_core_all_five_states_defined(index_html_content: str) -> None:
    """CSS must define animations and gradients for all 5 real UI states."""
    states = ["idle", "listening", "processing", "speaking", "error"]
    for state in states:
        assert f".state-{state}" in index_html_content, f"CSS rule for .state-{state} missing"

    # Verify keyframes for state transitions
    assert "@keyframes coreRotateCW" in index_html_content
    assert "@keyframes coreBreathe" in index_html_content
    assert "@keyframes coreListenPulse" in index_html_content
    assert "@keyframes coreProcessPulse" in index_html_content
    assert "@keyframes coreSpeakPulse" in index_html_content
    assert "@keyframes coreErrorGlow" in index_html_content


def test_astakos_core_reduced_motion_compliance(index_html_content: str) -> None:
    """prefers-reduced-motion media query must be respected to disable animations."""
    assert "@media (prefers-reduced-motion: reduce)" in index_html_content
    reduced_section = index_html_content.split("@media (prefers-reduced-motion: reduce)")[1].split("}")[0]
    assert "animation: none !important" in reduced_section


def test_core_state_js_engine_wiring(index_html_content: str) -> None:
    """JavaScript setCoreState must handle all 5 real states without fake transitions."""
    assert "function setCoreState(state)" in index_html_content
    assert "CORE_STATE_DETAILS" in index_html_content
    assert "'listening'" in index_html_content
    assert "'processing'" in index_html_content
    assert "'speaking'" in index_html_content
    assert "'error'" in index_html_content
    assert "'idle'" in index_html_content

    # Backward-compatible wrapper
    assert "function setAvatar(state)" in index_html_content


def test_tts_speaker_control_per_assistant_message(index_html_content: str) -> None:
    """Assistant messages must provide an on-demand speaker control without auto-play by default."""
    assert "msg-action-btn speak-btn" in index_html_content
    assert "toggleSpeakMessage" in index_html_content
    assert "fetch('/tts'" in index_html_content or 'fetch("/tts"' in index_html_content
    # Audio lifecycle
    assert "currentAudio.onended" in index_html_content
    assert "currentAudio.onerror" in index_html_content

    # Ensure no automatic speakText in standard sendMessage response
    assert "if (isDrawerOpen) speakText" not in index_html_content


def test_no_debug_urls_in_normal_frontend(index_html_content: str) -> None:
    """Normal frontend must not reference or call protected /debug endpoints."""
    # Ensure no /debug endpoint is queried or linked
    assert "/debug" not in index_html_content
    assert "handleApproveAction" not in index_html_content
    assert "handleRejectAction" not in index_html_content
    assert "debug_token" not in index_html_content


def test_no_fake_or_polling_status(index_html_content: str) -> None:
    """No simulated status deck, fake cards, or periodic runtime polling in normal UI."""
    assert "id=\"now-deck\"" not in index_html_content
    assert "renderNowDeck" not in index_html_content
    assert "refreshNowDeck" not in index_html_content
    assert "now-card-approval" not in index_html_content
    assert "now-card-draft" not in index_html_content
    assert "now-card-routine" not in index_html_content

    # Verify polling is strictly limited to chat sync via /messages/poll
    assert "/messages/poll" in index_html_content
    assert "fetchNewMessages" in index_html_content


def test_core_states_tied_to_real_lifecycle(index_html_content: str) -> None:
    """Astakos Core states must be wired strictly to real operational lifecycles."""
    # Listening: real mediaRecorder
    assert "mediaRecorder.start();" in index_html_content
    assert "setCoreState('listening')" in index_html_content

    # Processing: real server requests (/chat, /upload, /voice)
    assert "setCoreState('processing')" in index_html_content
    assert "fetch('/chat'" in index_html_content or 'fetch("/chat"' in index_html_content
    assert "fetch('/upload'" in index_html_content or 'fetch("/upload"' in index_html_content
    assert "fetch('/voice'" in index_html_content or 'fetch("/voice"' in index_html_content

    # Speaking: real Audio playback lifecycle
    assert "setCoreState('speaking')" in index_html_content
    assert "currentAudio = new Audio(audioUrl);" in index_html_content
    assert "await currentAudio.play();" in index_html_content

    # Error: real network / catch or audio failures
    assert "setCoreState('error')" in index_html_content

    # Idle: return on completion
    assert "setCoreState('idle')" in index_html_content


def test_voice_recording_visual_feedback(index_html_content: str) -> None:
    """Microphone button and Core must reflect real active recording state."""
    assert "mic-recording" in index_html_content
    assert "@keyframes micPulse" in index_html_content
    assert "setCoreState('listening')" in index_html_content
    assert "setCoreState('processing')" in index_html_content


def test_live_voice_mode_supports_automatic_turns_and_user_interruption(
    index_html_content: str,
) -> None:
    """Live mode must center the Core, send after silence, and support barge-in."""
    assert 'id="live-voice-btn"' in index_html_content
    assert "live-voice-active" in index_html_content
    assert "startLiveVoiceMode" in index_html_content
    assert "stopLiveVoiceMode" in index_html_content
    assert "LIVE_SILENCE_DURATION_MS" in index_html_content
    assert "startLiveSpeechMonitor" in index_html_content
    assert "startLiveInterruptionMonitor" in index_html_content
    assert "pauseLiveReplyForInterruption" in index_html_content
    assert "echoCancellation: true" in index_html_content
    assert "noiseSuppression: true" in index_html_content
    assert "window.addEventListener('keydown'" in index_html_content


def test_fastapi_serves_jarvis_index_html() -> None:
    """FastAPI server endpoint GET / must return status 200 with the redesigned interface."""
    from api.server import server

    client = TestClient(server, client=("127.0.0.1", 50000))
    response = client.get("/")
    assert response.status_code == 200
    assert "Astakos — AI Companion" in response.text
    assert "astakos-core-svg" in response.text
    assert "companion-hud" in response.text
    assert "/debug" not in response.text


def test_existing_web_routes_work() -> None:
    """Verify that existing core web routes continue to function properly."""
    from api.server import server

    client = TestClient(server, client=("127.0.0.1", 50000))

    # Health check
    res_health = client.get("/health")
    assert res_health.status_code == 200
    assert "status" in res_health.json()

    # Chat history endpoint
    res_hist = client.get("/history")
    assert res_hist.status_code == 200
    assert "history" in res_hist.json()

    # Polling endpoint for chat sync
    res_poll = client.get("/messages/poll?after_id=0")
    assert res_poll.status_code == 200
    poll_data = res_poll.json()
    assert "messages" in poll_data
    assert "max_id" in poll_data
