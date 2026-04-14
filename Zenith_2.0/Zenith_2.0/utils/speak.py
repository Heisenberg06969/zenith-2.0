import asyncio
import edge_tts
import pygame
import os
import queue
import tempfile
import threading
import time

BOT_NAME = "zenith"
# VOICE = "en-US-ChristopherNeural"
VOICE = "en-CA-LiamNeural"

pygame.mixer.init()
_tts_queue = queue.Queue()
_tts_worker = None
_tts_worker_lock = threading.Lock()


async def _speak_async(text: str):
    fd, filename = tempfile.mkstemp(prefix="zenith_tts_", suffix=".mp3")
    os.close(fd)
    try:
        communicate = edge_tts.Communicate(text, VOICE, rate="+10%")
        await communicate.save(filename)

        pygame.mixer.music.load(filename)
        pygame.mixer.music.play()

        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(30)
        pygame.mixer.music.unload()
    finally:
        try:
            if os.path.exists(filename):
                os.remove(filename)
        except PermissionError:
            pass


def _speak_now(text: str):
    if not text or not text.strip():
        return
    print(f"\033[96mZenith: {text}\033[0m")
    asyncio.run(_speak_async(text))


def _worker_loop():
    while True:
        item = _tts_queue.get()
        try:
            if item is None:
                return
            text, done_event = item
            _speak_now(text)
            if done_event is not None:
                done_event.set()
        finally:
            _tts_queue.task_done()


def _ensure_worker():
    global _tts_worker
    with _tts_worker_lock:
        if _tts_worker is None or not _tts_worker.is_alive():
            _tts_worker = threading.Thread(target=_worker_loop, daemon=True, name="ZenithTTSWorker")
            _tts_worker.start()


def speak(text: str):
    if not text or not text.strip():
        return
    _ensure_worker()
    done_event = threading.Event()
    _tts_queue.put((text, done_event))
    done_event.wait()


def speak_async(text: str):
    if not text or not text.strip():
        return
    _ensure_worker()
    _tts_queue.put((text, None))


def wait_for_speech_queue(timeout: float | None = None) -> bool:
    start = time.monotonic()
    while _tts_queue.unfinished_tasks > 0:
        if timeout is not None and (time.monotonic() - start) > timeout:
            return False
        time.sleep(0.02)
    return True
