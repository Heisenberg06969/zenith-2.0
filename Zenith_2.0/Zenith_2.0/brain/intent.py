def detect_intent(text: str):
    text = text.lower()

    open_words = ["open", "launch", "start", "khol", "kholo", "chalu"]
    search_words = ["search", "find", "dekhao"]

    # OPEN INTENT
    if any(word in text for word in open_words):
        for app in ["chrome", "youtube", "notepad", "spotify"]:
            if app in text:
                return {"action": "open_app", "target": app}

    # SEARCH INTENT
    if any(word in text for word in search_words):
        return {"action": "search_google", "target": text.replace("search", "").strip()}

    return None