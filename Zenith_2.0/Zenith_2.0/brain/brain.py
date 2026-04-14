# ============================================================
#   ZENITH BRAIN — Groq LLM Integration (Optimized)
# ============================================================

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable

from groq import Groq
from handlers.open_handler import handle_open
from handlers.search_handler import handle_search
from utils.speak import speak

# =========================
# API SETUP (SAFE)
# =========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)


def load_env_file():
    env_path = os.path.join(PROJECT_DIR, ".env")
    if not os.path.exists(env_path):
        return

    try:
        with open(env_path, "r", encoding="utf-8") as env_file:
            for line in env_file:
                clean_line = line.strip()
                if not clean_line or clean_line.startswith("#") or "=" not in clean_line:
                    continue

                key, value = clean_line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                os.environ.setdefault(key, value)
    except Exception as e:
        print(f"Error loading .env file: {e}")


load_env_file()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
PRIMARY_MODEL_TIMEOUT = float(os.getenv("ZENITH_PRIMARY_TIMEOUT_SEC", "12"))
LOCAL_LLM_ENDPOINT = os.getenv("ZENITH_LOCAL_LLM_ENDPOINT", "http://localhost:11434/api/generate")
LOCAL_LLM_MODEL = os.getenv("ZENITH_LOCAL_LLM_MODEL", "llama3.2:3b")
LOCAL_LLM_TIMEOUT = float(os.getenv("ZENITH_LOCAL_LLM_TIMEOUT_SEC", "20"))
LOCAL_LLM_FALLBACK_ENABLED = os.getenv("ZENITH_LOCAL_FALLBACK_ENABLED", "1").strip().lower() in {"1", "true", "yes"}

if GROQ_API_KEY:
    client = Groq(api_key=GROQ_API_KEY)
else:
    client = None
    print("\033[93mWarning: GROQ_API_KEY not found. Primary model disabled; local fallback will be used.\033[0m")


# =========================
# LOAD PERSONALITY
# =========================
COMPACT_SYSTEM_PROMPT = """You are Zenith Varyn, the user's personal AI assistant.
Rules:
- Address the user as "sir".
- Keep replies short, clear, and direct.
- No emojis.
- Reply in the user's language style (English/Bengali/Hinglish/Banglish).
- If you do not know, say exactly: "I don't know, sir." and do not attempt to guess, and explain what you don't know.
- For actionable commands (open/search/launch/play), reply only as JSON:
  {"action":"<action_name>","target":"<target_name>"}
- Allowed actions: open_app, open_site, search_google, search_youtube, unknown_command.
"""


def load_personality():
    path = os.path.join(BASE_DIR, "memory", "system", "personality.txt")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"Error loading personality: {e}")
        return "You are Zenith, an AI assistant."


USE_FULL_PERSONALITY = os.getenv("ZENITH_USE_FULL_PERSONALITY", "0").strip() in {"1", "true", "yes"}
SYSTEM_PROMPT = load_personality() if USE_FULL_PERSONALITY else COMPACT_SYSTEM_PROMPT


# =========================
# MEMORY (SHORT TERM)
# =========================
MAX_TURNS = int(os.getenv("ZENITH_MAX_TURNS", "4"))
MAX_CHARS_PER_MESSAGE = int(os.getenv("ZENITH_MAX_CHARS_PER_MESSAGE", "400"))
MAX_OUTPUT_TOKENS = int(os.getenv("ZENITH_MAX_OUTPUT_TOKENS", "160"))
MODEL_NAME = os.getenv("ZENITH_MODEL", "groq/compound") #"llama-3.3-70b-versatile"/"groq/compound"

messages = [
    {
        "role": "system",
        "content": SYSTEM_PROMPT
    }
]


def _clean_text(text: str, max_chars: int) -> str:
    clean = " ".join(text.split()).strip()
    return clean[:max_chars]


def _prune_history():
    max_messages = 1 + (MAX_TURNS * 2)
    while len(messages) > max_messages:
        messages.pop(1)


# =========================
# LLM RESPONSE
# =========================
def _primary_model_response() -> str:
    if client is None:
        raise RuntimeError("Primary model unavailable: GROQ_API_KEY missing.")

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        max_tokens=MAX_OUTPUT_TOKENS,
        temperature=0.4,
        timeout=PRIMARY_MODEL_TIMEOUT
    )

    content = response.choices[0].message.content or ""
    return content.strip()


def _extract_primary_chunk_text(chunk) -> str:
    try:
        choice = chunk.choices[0]
    except (AttributeError, IndexError, TypeError):
        return ""

    delta = getattr(choice, "delta", None)
    if delta is None and isinstance(choice, dict):
        delta = choice.get("delta")
    if delta is None:
        return ""

    if isinstance(delta, dict):
        content = delta.get("content")
    else:
        content = getattr(delta, "content", "")
    return content or ""


def _primary_model_stream_response(on_chunk: Callable[[str], None] | None = None) -> str:
    if client is None:
        raise RuntimeError("Primary model unavailable: GROQ_API_KEY missing.")

    stream = client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        max_tokens=MAX_OUTPUT_TOKENS,
        temperature=0.4,
        timeout=PRIMARY_MODEL_TIMEOUT,
        stream=True
    )

    parts = []
    for chunk in stream:
        text = _extract_primary_chunk_text(chunk)
        if not text:
            continue
        parts.append(text)
        if on_chunk is not None:
            on_chunk(text)

    return "".join(parts).strip()


def _extract_local_llm_text(payload_text: str) -> str:
    payload_text = payload_text.strip()
    if not payload_text:
        return ""

    # stream=False returns one JSON object
    try:
        data = json.loads(payload_text)
        if isinstance(data, dict):
            return (data.get("response") or "").strip()
    except json.JSONDecodeError:
        pass

    # Fallback parser for streamed JSONL chunks
    parts = []
    for line in payload_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            if isinstance(data, dict):
                chunk = data.get("response")
                if chunk:
                    parts.append(chunk)
        except json.JSONDecodeError:
            continue

    return "".join(parts).strip()


def _iter_local_llm_stream_chunks(user_input: str):
    if not LOCAL_LLM_FALLBACK_ENABLED:
        return

    payload = json.dumps({
        "model": LOCAL_LLM_MODEL,
        "prompt": user_input,
        "stream": True,
        "options": {"temperature": 0.4}
    }).encode("utf-8")

    request = urllib.request.Request(
        LOCAL_LLM_ENDPOINT,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(request, timeout=LOCAL_LLM_TIMEOUT) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="ignore").strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                continue

            piece = data.get("response")
            if piece:
                yield piece

            if data.get("done"):
                break


def llama_local_response(user_input: str) -> str:
    if not LOCAL_LLM_FALLBACK_ENABLED:
        return ""

    payload = json.dumps({
        "model": LOCAL_LLM_MODEL,
        "prompt": user_input,
        "stream": False,
        "options": {"temperature": 0.4}
    }).encode("utf-8")

    request = urllib.request.Request(
        LOCAL_LLM_ENDPOINT,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(request, timeout=LOCAL_LLM_TIMEOUT) as response:
        body = response.read().decode("utf-8", errors="ignore")

    return _extract_local_llm_text(body)


def _generate_with_fallback(
    user_msg: str,
    on_chunk: Callable[[str], None] | None = None,
    on_fallback_activated: Callable[[], None] | None = None
) -> str:
    primary_error = None

    try:
        if on_chunk is None:
            primary_reply = _primary_model_response()
        else:
            primary_reply = _primary_model_stream_response(on_chunk)
        if primary_reply:
            return primary_reply
    except Exception as error:
        primary_error = error
        print(f"\033[91mPrimary model error: {error}\033[0m")

    try:
        if on_fallback_activated is not None:
            on_fallback_activated()

        if on_chunk is None:
            fallback_reply = llama_local_response(user_msg)
        else:
            fallback_parts = []
            for piece in _iter_local_llm_stream_chunks(user_msg):
                fallback_parts.append(piece)
                on_chunk(piece)
            fallback_reply = "".join(fallback_parts).strip()

        if fallback_reply:
            print("\033[93mFallback → Llama 3.2 activated\033[0m")
            return fallback_reply
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as fallback_error:
        print(f"\033[91mLocal fallback error: {fallback_error}\033[0m")
        if primary_error is None:
            primary_error = fallback_error

    if primary_error is not None:
        raise primary_error

    raise RuntimeError("Both primary and fallback models returned an empty response.")


def get_response(user_input: str) -> str:
    user_msg = _clean_text(user_input, MAX_CHARS_PER_MESSAGE)
    messages.append({"role": "user", "content": user_msg})
    _prune_history()

    try:
        reply = _generate_with_fallback(user_msg)

        # Store reply
        assistant_msg = _clean_text(reply, MAX_CHARS_PER_MESSAGE)
        messages.append({"role": "assistant", "content": assistant_msg})
        _prune_history()

        return reply

    except Exception as e:
        print(f"\033[91mBrain Error: {e}\033[0m")
        return f"I encountered an error, sir {e}."


def get_response_stream(
    user_input: str,
    on_chunk: Callable[[str], None] | None = None,
    on_fallback_activated: Callable[[], None] | None = None
) -> str:
    user_msg = _clean_text(user_input, MAX_CHARS_PER_MESSAGE)
    messages.append({"role": "user", "content": user_msg})
    _prune_history()

    try:
        reply = _generate_with_fallback(
            user_msg,
            on_chunk=on_chunk,
            on_fallback_activated=on_fallback_activated
        )

        assistant_msg = _clean_text(reply, MAX_CHARS_PER_MESSAGE)
        messages.append({"role": "assistant", "content": assistant_msg})
        _prune_history()
        return reply

    except Exception as e:
        print(f"\033[91mBrain Error: {e}\033[0m")
        return f"I encountered an error, sir {e}."


# =========================
# COMMAND DETECTION
# =========================
def is_command(reply: str) -> dict | None:
    clean = reply.replace("```json", "").replace("```", "").strip()

    try:
        data = json.loads(clean)
        if isinstance(data, dict) and "action" in data:
            return data
    except:
        pass

    return None


# =========================
# COMMAND EXECUTION
# =========================
def execute_command(command: dict):
    action = command.get("action")
    target = command.get("target", "")

    if action == "open_app":
        result = handle_open(f"open {target}")
        if not result:
            speak(f"I couldn't find {target}, sir.")

    elif action == "open_site":
        result = handle_open(f"open {target}")
        if not result:
            speak(f"I couldn't find {target}, sir.")

    elif action == "search_google":
        handle_search(f"search {target}")

    elif action == "search_youtube":
        handle_search(f"search {target} on youtube")

    elif action == "unknown_command":
        speak("I could not understand that command, sir.")

    else:
        speak("Command not recognized, sir.")
