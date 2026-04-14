from utils.speak import speak
import webbrowser
import os
from config.websites import WEBSITES
from config.apps import APPS


def handle_open(text: str) -> bool:
    # Website
    for name, url in WEBSITES.items():
        if name in text:
            speak(f"Opening {name}, sir.")
            webbrowser.open(url)
            return True

    # App
    for name, path in APPS.items():
        if name in text:
            speak(f"Opening {name}, sir.")
            os.startfile(path)
            return True

    return False
