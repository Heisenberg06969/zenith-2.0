# ============================================================
#   ZENITH 2.0 - Voice + LLM + Modular Command System
#   Created by: Niloy Das
# ============================================================

import json
import os
import threading
import time
from collections import deque
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import speech_recognition as sr

from brain.brain import execute_command, get_response_stream, is_command
from brain.intent import detect_intent
from utils.speak import speak, speak_async, wait_for_speech_queue

try:
    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtGui import QIcon
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication, QMainWindow
except ImportError:
    QTimer = None
    QUrl = None
    QIcon = None
    QWebEngineView = None
    QApplication = None
    QMainWindow = object


PROJECT_DIR = Path(__file__).resolve().parent
GUI_FILE = PROJECT_DIR / "gui" / "zenith_gui_v4.html"
ICON_FILE = PROJECT_DIR / "gui" / "assets" / "zenith_icon.png"
GUI_HOST = os.getenv("ZENITH_GUI_HOST", "127.0.0.1")
GUI_PORT = int(os.getenv("ZENITH_GUI_PORT", "8765"))
GUI_ENABLED = os.getenv("ZENITH_ENABLE_GUI", "1").strip().lower() not in {"0", "false", "no"}
DESKTOP_ENABLED = os.getenv("ZENITH_DESKTOP_MODE", "1").strip().lower() not in {"0", "false", "no"}

WAKE_WORDS = [
    "ok zenith", "wake up zenith", "wake up", "hey zenith", "wake up bro", "yo zenith",
    "zenith wake up", "ok bro", "hey bro", "yo bro", "bro wake up",
    "ok buddy", "hey buddy", "yo buddy", "buddy wake up", "wake up buddy"
]

gui_state = {
    "mode": "idle",
    "status": "Booting",
    "heard": "",
    "last_reply": "",
    "activated": False,
    "updated_at": datetime.now(timezone.utc).isoformat()
}
gui_state_lock = threading.Lock()
gui_events = deque(maxlen=500)
gui_event_counter = 0


def push_gui_event(event_type: str, **payload):
    global gui_event_counter
    with gui_state_lock:
        gui_event_counter += 1
        gui_events.append({
            "id": gui_event_counter,
            "type": event_type,
            "payload": payload,
            "at": datetime.now(timezone.utc).isoformat()
        })


def get_gui_events_since(since_id: int) -> list[dict]:
    with gui_state_lock:
        return [evt for evt in gui_events if evt["id"] > since_id]


def update_gui_state(
    *,
    mode: str | None = None,
    status: str | None = None,
    heard: str | None = None,
    last_reply: str | None = None,
    activated_state: bool | None = None
):
    with gui_state_lock:
        if mode is not None:
            gui_state["mode"] = mode
        if status is not None:
            gui_state["status"] = status
        if heard is not None:
            gui_state["heard"] = heard
        if last_reply is not None:
            gui_state["last_reply"] = last_reply
        if activated_state is not None:
            gui_state["activated"] = activated_state
        gui_state["updated_at"] = datetime.now(timezone.utc).isoformat()


def start_gui_server():
    if not GUI_ENABLED:
        print("\033[90mGUI disabled (ZENITH_ENABLE_GUI=0)\033[0m")
        return None, None

    if not GUI_FILE.exists():
        print(f"\033[91mGUI file not found: {GUI_FILE}\033[0m")
        return None, None

    class ZenithGUIHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(PROJECT_DIR), **kwargs)

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/api/state":
                with gui_state_lock:
                    payload = json.dumps(gui_state).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if parsed.path == "/api/events":
                query = parse_qs(parsed.query)
                try:
                    since = int(query.get("since", ["0"])[0])
                except ValueError:
                    since = 0

                payload = json.dumps({"events": get_gui_events_since(since)}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            super().do_GET()

        def log_message(self, _format, *_args):
            return

    try:
        server = ThreadingHTTPServer((GUI_HOST, GUI_PORT), ZenithGUIHandler)
    except OSError as error:
        print(f"\033[91mGUI server failed: {error}\033[0m")
        return None, None

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    url = f"http://{GUI_HOST}:{GUI_PORT}/gui/zenith_gui_v4.html"
    print(f"\033[92mGUI server running at: {url}\033[0m")
    return server, url


class ZenithWindow(QMainWindow):
    def __init__(self, url: str, stop_event: threading.Event):
        super().__init__()
        self._stop_event = stop_event

        self.setWindowTitle("Zenith")
        self.resize(1440, 860)
        self.setMinimumSize(1100, 680)
        if ICON_FILE.exists() and QIcon is not None:
            self.setWindowIcon(QIcon(str(ICON_FILE)))

        self.view = QWebEngineView(self)
        self.view.setUrl(QUrl(url))
        self.setCentralWidget(self.view)

    def closeEvent(self, event):
        self._stop_event.set()
        super().closeEvent(event)


def run_voice_loop(stop_event: threading.Event, app_exit_event: threading.Event):
    class SentenceStreamer:
        def __init__(self):
            self.buffer = ""

        def push(self, chunk: str):
            if not chunk:
                return
            self.buffer += chunk
            self._emit_complete_sentences()

        def _emit_complete_sentences(self):
            while True:
                sentence_end = -1
                for idx, ch in enumerate(self.buffer):
                    if ch == "\n":
                        sentence_end = idx
                        break
                    if ch in ".!?":
                        next_is_boundary = idx == len(self.buffer) - 1 or self.buffer[idx + 1].isspace()
                        if next_is_boundary:
                            sentence_end = idx
                            break

                if sentence_end < 0:
                    return

                sentence = self.buffer[:sentence_end + 1].strip()
                self.buffer = self.buffer[sentence_end + 1:].lstrip()
                if sentence:
                    speak_async(sentence)

        def flush(self):
            final_text = self.buffer.strip()
            self.buffer = ""
            if final_text:
                speak_async(final_text)

    activated = False
    recognizer = sr.Recognizer()
    recognizer.pause_threshold = 2

    print("\033[96mZenith 2.0 - Online\033[0m")

    try:
        while not stop_event.is_set():
            with sr.Microphone() as source:
                if activated:
                    print("\033[93mListening for command...\033[0m")
                    update_gui_state(
                        mode="listen",
                        status="Listening for command",
                        activated_state=True
                    )
                else:
                    print("\033[93mWaiting for wake word...\033[0m")
                    update_gui_state(
                        mode="idle",
                        status="Waiting for wake word",
                        activated_state=False
                    )

                recognizer.pause_threshold = 2
                try:
                    audio = recognizer.listen(source, timeout=2, phrase_time_limit=10)
                except sr.WaitTimeoutError:
                    continue

            try:
                update_gui_state(mode="think", status="Processing speech")
                text = recognizer.recognize_google(audio).lower()
                update_gui_state(heard=text)
                push_gui_event("user_message", text=text)
                print(f"\033[97mYou: {text}\033[0m")

                if not activated:
                    if any(word in text for word in WAKE_WORDS):
                        activated = True
                        reply = "Activated. How can I assist, sir."
                        update_gui_state(
                            mode="speak",
                            status="Activated",
                            last_reply=reply,
                            activated_state=True
                        )
                        speak(reply)
                        update_gui_state(mode="listen", status="Ready", activated_state=True)
                    else:
                        update_gui_state(mode="idle", status="Wake word not detected", activated_state=False)
                    continue

                if "sleep" in text:
                    reply = "Going to sleep, sir."
                    update_gui_state(mode="speak", status="Entering sleep mode", last_reply=reply, activated_state=True)
                    speak(reply)
                    activated = False
                    update_gui_state(mode="idle", status="Sleeping", activated_state=False)
                    continue

                if "stop" in text or "exit" in text:
                    reply = "Goodbye, sir."
                    update_gui_state(mode="speak", status="Shutting down", last_reply=reply, activated_state=True)
                    speak(reply)
                    update_gui_state(mode="idle", status="Offline", activated_state=False)
                    stop_event.set()
                    app_exit_event.set()
                    break

                if len(text.strip()) < 2:
                    update_gui_state(mode="listen", status="Ready", activated_state=True)
                    continue

                intent = detect_intent(text)
                if intent:
                    action = intent.get("action", "command")
                    update_gui_state(mode="think", status=f"Executing intent: {action}", activated_state=True)
                    execute_command(intent)
                    update_gui_state(
                        mode="listen",
                        status="Command executed",
                        last_reply=f"Executed {action}",
                        activated_state=True
                    )
                    continue

                speaker = SentenceStreamer()
                stream_started = False
                fallback_activated = False

                def on_chunk(chunk: str):
                    nonlocal stream_started
                    if not stream_started:
                        stream_started = True
                        update_gui_state(mode="speak", status="Speaking", activated_state=True)
                        push_gui_event("assistant_stream_start")
                    push_gui_event("assistant_stream_chunk", chunk=chunk)
                    speaker.push(chunk)

                def on_fallback():
                    nonlocal fallback_activated
                    if fallback_activated:
                        return
                    fallback_activated = True
                    push_gui_event("system_message", text="Fallback → Local LLM activated")

                reply = get_response_stream(
                    text,
                    on_chunk=on_chunk,
                    on_fallback_activated=on_fallback
                )

                if reply and not stream_started:
                    update_gui_state(mode="speak", status="Speaking", activated_state=True)
                    push_gui_event("assistant_stream_start")
                    push_gui_event("assistant_stream_chunk", chunk=reply)
                    speaker.push(reply)

                command = is_command(reply)
                if command:
                    push_gui_event("assistant_stream_end")
                    action = command.get("action", "command")
                    update_gui_state(mode="think", status=f"Executing command: {action}", activated_state=True)
                    execute_command(command)
                    update_gui_state(
                        mode="listen",
                        status="Command executed",
                        last_reply=f"Executed {action}",
                        activated_state=True
                    )
                else:
                    speaker.flush()
                    wait_for_speech_queue(timeout=60.0)
                    push_gui_event("assistant_stream_end")
                    update_gui_state(mode="speak", status="Speaking", last_reply=reply, activated_state=True)
                    update_gui_state(mode="listen", status="Ready", activated_state=True)

            except sr.UnknownValueError:
                status = "Could not understand audio"
                print(f"\033[91m{status}\033[0m")
                push_gui_event("error_message", text=status)
                update_gui_state(
                    mode="listen" if activated else "idle",
                    status=status,
                    activated_state=activated
                )
            except Exception as error:
                print(f"\033[91mError: {error}\033[0m")
                push_gui_event("error_message", text=f"Error: {error}")
                update_gui_state(
                    mode="listen" if activated else "idle",
                    status=f"Error: {error}",
                    activated_state=activated
                )
    finally:
        update_gui_state(mode="idle", status="Offline", activated_state=False)


def run_desktop_app(url: str, stop_event: threading.Event, app_exit_event: threading.Event):
    if QApplication is None or QWebEngineView is None:
        raise RuntimeError(
            "PySide6 with QtWebEngine is not installed. Install it with: pip install PySide6"
        )

    app = QApplication([])
    if ICON_FILE.exists() and QIcon is not None:
        app.setWindowIcon(QIcon(str(ICON_FILE)))

    window = ZenithWindow(url, stop_event)
    window.show()

    checker = QTimer()
    checker.setInterval(200)

    def poll_exit():
        if app_exit_event.is_set():
            app.quit()

    checker.timeout.connect(poll_exit)
    checker.start()

    app.exec()


def main():
    gui_server, gui_url = start_gui_server()
    update_gui_state(mode="idle", status="Online", activated_state=False)

    stop_event = threading.Event()
    app_exit_event = threading.Event()

    voice_thread = threading.Thread(
        target=run_voice_loop,
        args=(stop_event, app_exit_event),
        daemon=True
    )
    voice_thread.start()

    try:
        if GUI_ENABLED and DESKTOP_ENABLED and gui_url:
            run_desktop_app(gui_url, stop_event, app_exit_event)
        elif GUI_ENABLED and gui_url:
            print(f"\033[93mDesktop mode disabled. Open manually: {gui_url}\033[0m")
            while not stop_event.is_set():
                time.sleep(0.2)
        else:
            while not stop_event.is_set():
                time.sleep(0.2)
    finally:
        stop_event.set()
        app_exit_event.set()
        voice_thread.join(timeout=2)
        if gui_server is not None:
            gui_server.shutdown()
            gui_server.server_close()
        update_gui_state(mode="idle", status="Offline", activated_state=False)


if __name__ == "__main__":
    main()
