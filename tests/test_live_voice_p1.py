import array
import math
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import Settings
from live_voice import (
    AsyncAudioPlayer,
    LiveVoiceSession,
    _apply_volume_gain,
    _calculate_pcm_rms,
)


def test_soft_knee_volume_limiter_bounds():
    """Verify soft limiter prevents integer overflow and distortion."""
    # 1. Zero stays zero
    zero_pcm = array.array("h", [0, 0, 0]).tobytes()
    assert _apply_volume_gain(zero_pcm, gain=2.0) == zero_pcm

    # 2. Linear region (< 24000) boosted accurately
    linear_pcm = array.array("h", [5000, -5000]).tobytes()
    boosted = _apply_volume_gain(linear_pcm, gain=1.5)
    samples = array.array("h", boosted)
    assert samples[0] == 7500
    assert samples[1] == -7500

    # 3. Peak values never exceed 32767 or wrap around to negative
    extreme_pcm = array.array("h", [30000, 32767, -30000, -32768]).tobytes()
    boosted_extreme = _apply_volume_gain(extreme_pcm, gain=3.0)
    extreme_samples = array.array("h", boosted_extreme)
    for s in extreme_samples:
        assert -32768 <= s <= 32767
    assert extreme_samples[0] > 24000
    assert extreme_samples[1] > 24000
    assert extreme_samples[2] < -24000
    assert extreme_samples[3] < -24000


def test_calculate_pcm_rms():
    """Verify RMS energy calculation."""
    # Silence has 0 RMS
    silence = array.array("h", [0] * 160).tobytes()
    assert _calculate_pcm_rms(silence) == 0.0

    # Constant signal RMS equals amplitude
    const_signal = array.array("h", [1000] * 160).tobytes()
    assert abs(_calculate_pcm_rms(const_signal) - 1000.0) < 1.0

    # Low noise vs speech energy distinction
    noise = array.array("h", [150, -150] * 80).tobytes()
    speech = array.array("h", [2500, -2500] * 80).tobytes()
    assert _calculate_pcm_rms(noise) < 300
    assert _calculate_pcm_rms(speech) > 2000


def test_async_audio_player_queue_and_barge_in():
    """Verify AsyncAudioPlayer queues chunks and instantly purges on barge-in."""
    mock_pyaudio = MagicMock()
    mock_stream = MagicMock()
    mock_pyaudio.PyAudio.return_value.open.return_value = mock_stream
    mock_pyaudio.paInt16 = 1

    settings = Settings(
        api_key="test_key",
        live_audio_gain=1.6,
        live_vad_energy_threshold=350,
        live_echo_gate_multiplier=2.5,
    )

    player = AsyncAudioPlayer(settings, pyaudio_module=mock_pyaudio)
    try:
        sample_chunk = array.array("h", [1000] * 480).tobytes()

        # Push multiple chunks
        for _ in range(5):
            player.push(sample_chunk)

        assert player.is_playing is True

        # Test barge-in purge
        player.barge_in_purge()
        assert player.is_playing is False
        assert player._queue.empty() is True
    finally:
        player.close()


def test_live_voice_session_initialization():
    """Verify LiveVoiceSession config and player creation."""
    mock_pyaudio = MagicMock()
    settings = Settings(
        api_key="test_key",
        live_voice="Orus",
        live_vad_energy_threshold=400,
        live_echo_gate_multiplier=3.0,
    )

    session = LiveVoiceSession(settings, pyaudio_module=mock_pyaudio)
    try:
        assert session._player is not None
        assert session._player.settings.live_vad_energy_threshold == 400
        assert session._player.settings.live_echo_gate_multiplier == 3.0
    finally:
        session.close()


def test_live_voice_callbacks():
    """Verify LiveVoiceCallbacks receive event triggers."""
    from live_voice import LiveVoiceCallbacks

    user_transcripts = []
    model_transcripts = []

    callbacks = LiveVoiceCallbacks(
        on_user_transcript=lambda txt: user_transcripts.append(txt),
        on_model_transcript=lambda txt: model_transcripts.append(txt),
    )

    mock_pyaudio = MagicMock()
    settings = Settings(api_key="test_key")
    session = LiveVoiceSession(settings, pyaudio_module=mock_pyaudio, callbacks=callbacks)
    try:
        session._input_text_chunks.append("Hello DarkShadow")
        session._flush_input_transcription()
        assert user_transcripts == ["Hello DarkShadow"]

        session._output_text_chunks.append("Namaste Captain")
        session._flush_output_transcription()
        assert model_transcripts == ["Namaste Captain"]
    finally:
        session.close()


def test_echo_gate_cooldown_and_queue_detection():
    """Verify AsyncAudioPlayer stays in is_playing state during cooldown and non-empty queue."""
    mock_pyaudio = MagicMock()
    mock_stream = MagicMock()
    mock_pyaudio.PyAudio.return_value.open.return_value = mock_stream

    settings = Settings(
        api_key="test_key",
        live_echo_gate_cooldown_seconds=0.65,
    )
    player = AsyncAudioPlayer(settings, pyaudio_module=mock_pyaudio)
    try:
        # Initially not playing
        assert player.is_playing is False

        # Directly simulate a playback timestamp within the 0.65s cooldown
        player._last_playback_time = time.monotonic()
        assert player.is_playing is True

        # Timestamp far in the past should not be considered playing
        player._last_playback_time = time.monotonic() - 1.0
        assert player.is_playing is False

        # Queue has item -> must report is_playing is True even if playback thread hasn't popped it
        player._queue.put(b"test_chunk")
        assert player.is_playing is True

        # Barge-in purge must reset everything
        player.barge_in_purge()
        assert player.is_playing is False
        assert player._queue.empty() is True
    finally:
        player.close()


def test_live_voice_echo_suppression_settings():
    """Verify default Settings have live_barge_in=False and live_echo_gate_cooldown_seconds=0.65."""
    settings = Settings(api_key="test_key")
    assert settings.live_barge_in is False
    assert settings.live_echo_gate_cooldown_seconds == 0.65


def test_model_turn_active_tracking():
    """Verify LiveVoiceSession initializes with model_turn_active=False and stop() resets it."""
    mock_pyaudio = MagicMock()
    settings = Settings(api_key="test_key")
    session = LiveVoiceSession(settings, pyaudio_module=mock_pyaudio)
    try:
        assert session._model_turn_active is False
        session._model_turn_active = True
        session.stop()
        assert session._model_turn_active is False
    finally:
        session.close()


if __name__ == "__main__":
    print("Running test_soft_knee_volume_limiter_bounds...")
    test_soft_knee_volume_limiter_bounds()
    print("PASSED")

    print("Running test_calculate_pcm_rms...")
    test_calculate_pcm_rms()
    print("PASSED")

    print("Running test_async_audio_player_queue_and_barge_in...")
    test_async_audio_player_queue_and_barge_in()
    print("PASSED")

    print("Running test_echo_gate_cooldown_and_queue_detection...")
    test_echo_gate_cooldown_and_queue_detection()
    print("PASSED")

    print("Running test_live_voice_echo_suppression_settings...")
    test_live_voice_echo_suppression_settings()
    print("PASSED")

    print("Running test_model_turn_active_tracking...")
    test_model_turn_active_tracking()
    print("PASSED")

    print("Running test_live_voice_session_initialization...")
    test_live_voice_session_initialization()
    print("PASSED")

    print("Running test_live_voice_callbacks...")
    test_live_voice_callbacks()
    print("PASSED")

    print("\nALL LIVE VOICE TESTS PASSED SUCCESSFULLY! [OK]")
