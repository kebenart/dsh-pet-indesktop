"""后台生成语音响度副本，原始缓存不改写；GUI 只查副本是否存在。"""
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from itertools import islice
import uuid

log = logging.getLogger(__name__)
MARK = '.voice-loudness-v1'


def normalized_path(path):
    path = Path(path)
    return path if MARK in path.stem else path.with_name(path.stem + MARK + path.suffix)


def playback_path(path):
    candidate = normalized_path(path)
    try:
        return str(candidate) if candidate.is_file() and candidate.stat().st_size > 0 else str(path)
    except OSError:
        return str(path)


def prepare(path):
    """只在合成 worker / 显式缓存准备中调用；失败回落原音，最多耗时8秒。"""
    path = Path(path)
    clip_module = sys.modules.get('pet.webm_clip')
    if clip_module is not None and clip_module.session_ending():
        return str(path)
    out = normalized_path(path)
    try:
        if out == path or (out.is_file() and out.stat().st_size > 0) or path.suffix.lower() not in ('.mp3', '.wav', '.ogg', '.flac') or path.stat().st_size < 256:
            return playback_path(path)
    except OSError:
        return str(path)
    temp = out.with_name(out.stem + '.' + uuid.uuid4().hex[:12] + out.suffix)
    try:
        import imageio_ffmpeg
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
                        '-i', str(path), '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11', '-ar', '24000', str(temp)],
                       check=True, timeout=8, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}))
        if temp.is_file() and temp.stat().st_size:
            os.replace(temp, out)
            return str(out)
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning('语音响度处理失败，使用原音: %s', type(exc).__name__)
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            log.warning('语音响度临时文件清理失败')
    return str(path)


def warm_cached_audio(directories):
    """为旧缓存后台补响度副本：单线程、最多128个候选、15秒起手预算。"""
    candidates = []
    for directory in directories:
        try:
            for path in islice(Path(directory).iterdir(), 128):
                if (path.suffix in ('.mp3', '.wav') and MARK not in path.stem
                        and path.is_file() and path.stat().st_size >= 256 and not normalized_path(path).exists()):
                    candidates.append(path)
        except OSError:
            continue
    cancel = threading.Event()
    if not candidates:
        return cancel

    def run():
        deadline = time.monotonic() + 15
        for path in candidates[:128]:
            if cancel.is_set() or time.monotonic() > deadline:
                break
            prepare(path)
    threading.Thread(target=run, daemon=True, name='voice-loudness-cache').start()
    return cancel
