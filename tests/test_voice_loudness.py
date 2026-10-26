import array
import math
from pathlib import Path
import wave

from pet.voice.loudness import prepare, playback_path, normalized_path


def test_quiet_audio_is_normalized_without_touching_original(tmp_path):
    source = tmp_path / 'quiet.wav'
    samples = array.array('h', [round(200 * math.sin(i * 2 * math.pi * 440 / 24000)) for i in range(24000)])
    with wave.open(str(source), 'wb') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(24000)
        f.writeframes(samples.tobytes())
    original = source.read_bytes()
    output = Path(prepare(source))
    assert output != source and output.is_file()
    assert source.read_bytes() == original
    with wave.open(str(output), 'rb') as f:
        data = array.array('h', f.readframes(f.getnframes()))
    rms = math.sqrt(sum(x * x for x in data) / len(data))
    assert rms > 1000  # 原音 RMS 约141，处理后声音应可辨且没有削波。
    assert max(abs(x) for x in data) < 32767
    assert prepare(source) == str(output)
    assert playback_path(source) == str(output)


def test_invalid_audio_falls_back_and_keeps_source(tmp_path):
    source = tmp_path / 'invalid.mp3'
    source.write_bytes(b'not an audio file' * 30)
    assert prepare(source) == str(source)
    assert not normalized_path(source).exists()
    assert source.is_file()
