# Zenith 2.0

**Voice + LLM + Modular Command System**

---

## Structure

```
Zenith_2.0/
│   zenith_main.py       ← Entry point
│   zenith.bat           ← Windows launcher
│   requirements.txt
│
├───brain/
│       brain.py         ← Groq LLM integration + command parser
│
├───handlers/
│       open_handler.py  ← Opens apps & websites
│       search_handler.py← Google & YouTube search
│
├───config/
│       apps.py          ← App paths
│       websites.py      ← Website URLs
│
└───utils/
        speak.py         ← Edge TTS voice output
```

---

## Setup

1. Install dependencies:
```
pip install -r requirements.txt
```

2. Set your Groq API key in `.env` (recommended):
```
GROQ_API_KEY=your_key_here
```

Optional token-saving settings in `.env`:
```
ZENITH_USE_FULL_PERSONALITY=0
ZENITH_MAX_TURNS=4
ZENITH_MAX_CHARS_PER_MESSAGE=400
ZENITH_MAX_OUTPUT_TOKENS=160
```

- `ZENITH_USE_FULL_PERSONALITY=0` uses a compact system prompt (recommended for lower token usage).
- `ZENITH_MAX_TURNS` controls how many recent user/assistant turns are sent to Groq.
- `ZENITH_MAX_CHARS_PER_MESSAGE` trims long messages before storing in memory.
- `ZENITH_MAX_OUTPUT_TOKENS` limits reply length.

Or set it as an environment variable:
```
set GROQ_API_KEY=your_key_here
```

3. Run:
```
zenith.bat
```
or
```
python zenith_main.py
```

GUI behavior (default):
- Zenith auto-hosts the GUI at `http://127.0.0.1:8765/gui/zenith_gui_v4.html`
- Browser opens automatically on startup
- GUI mode now syncs live with runtime state: `idle`, `listen`, `think`, `speak`

Optional GUI controls:
```
ZENITH_ENABLE_GUI=0
ZENITH_GUI_PORT=8765
ZENITH_GUI_HOST=127.0.0.1
```

---

## Voice Commands

| Command | Action |
|---|---|
| "ok zenith" | Activate |
| "sleep" | Deactivate |
| "stop" / "exit" | Shutdown |
| "open notepad" | Opens app |
| "open youtube" | Opens website |
| "search X on youtube" | YouTube search |
| "search X" | Google search |
| Anything else | LLM responds |

---

## How it works

```
Mic Input
   ↓
Speech to Text (Google STT)
   ↓
Groq LLM (compound-beta) — Zenith personality
   ↓
JSON command? → Handler (open/search)
Normal reply? → speak() → Edge TTS voice
```

---

*Zenith — Built by Niloy Das*
