"""
Hlasový výstup pro PC editor – accessible_output2.Auto() s fallbackem.
Port settings_page.dart:108 _speak() + respekt k čtečce.
"""
try:
    from accessible_output2.outputs.auto import Auto as _Auto
    _HAS_AO2 = True
except Exception:
    _Auto = None
    _HAS_AO2 = False

_speaker = None
_enabled = True

def _get_speaker():
    global _speaker
    if _speaker is not None:
        return _speaker
    if _HAS_AO2 and _Auto is not None:
        try:
            _speaker = _Auto()
        except Exception:
            _speaker = None
    return _speaker

def set_enabled(enabled: bool):
    global _enabled
    _enabled = bool(enabled)

def is_enabled() -> bool:
    return bool(_enabled)

def speak(text: str, interrupt: bool = False):
    """Vysloví text přes aktivní čtečku (NVDA/JAWS) nebo SAPI fallback. Tiché selhání."""
    if not _enabled or not text:
        return
    txt = str(text).strip()
    if not txt:
        return
    spk = _get_speaker()
    if spk is not None:
        try:
            # accessible_output2: speak(text, interrupt=bool)
            try:
                spk.speak(txt, interrupt=interrupt)
            except TypeError:
                spk.speak(txt)
            return
        except Exception:
            pass
    # fallback QTextToSpeech pokud accessible_output2 není
    try:
        from PyQt6.QtTextToSpeech import QTextToSpeech
        eng = QTextToSpeech()
        eng.setLocale("cs-CZ")
        eng.say(txt)
    except Exception:
        pass
