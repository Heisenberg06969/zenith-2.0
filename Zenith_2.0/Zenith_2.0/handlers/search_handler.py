from utils.speak import speak
import webbrowser


def google_search(query: str):
    url = f"https://www.google.com/search?q={query.strip().replace(' ', '+')}"
    webbrowser.open(url)


def youtube_search(query: str):
    url = f"https://www.youtube.com/results?search_query={query.strip().replace(' ', '+')}"
    webbrowser.open(url)


def handle_search(text: str) -> bool:
    if "search" not in text:
        return False

    if "on youtube" in text or "on you tube" in text:
        query = text.split("search", 1)[1]
        query = query.replace("on youtube", "").replace("on you tube", "").strip()
        if query:
            speak(f"Searching YouTube for {query}, sir.")
            youtube_search(query)
        else:
            speak("What should I search on YouTube, sir?")
        return True

    query = text.split("search", 1)[1].strip()
    if query:
        speak(f"Searching Google for {query}, sir.")
        google_search(query)
    else:
        speak("What should I search, sir?")
    return True
