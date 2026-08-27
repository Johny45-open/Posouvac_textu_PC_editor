"""
Hlasový výstup pro PC editor – více enginů.

Enginy:
  auto  – accessible_output2.Auto() (NVDA/JAWS/SAPI) offline
  edge  – edge-tts (online, kvalitní cs-CZ Vlasta/Antonin)
  gtts  – gTTS Google (online, cs)

Společné API: set_enabled, is_enabled, set_engine, get_engine,
              set_edge_voice, get_edge_voice, speak, stop,
              get_available_engines, set_fallback_callback.

Online enginy běží v background threadu (fronta) + přehrání přes
audio_player (QtMultimedia QMediaPlayer v main threadu). Při selhání
sítě fallback na auto. interrupt=True vyprázdní frontu + stop playeru.
"""
import os
import sys
import queue
import threading
import tempfile
import traceback

# --- detection ---
try:
    from accessible_output2.outputs.auto import Auto as _Auto
    _HAS_AO2 = True
except Exception:
    _Auto = None
    _HAS_AO2 = False

_HAS_EDGE = False
_HAS_GTTS = False
try:
    import edge_tts  # noqa: F401
    _HAS_EDGE = True
except Exception:
    _HAS_EDGE = False
try:
    import gtts  # noqa: F401
    _HAS_GTTS = True
except Exception:
    _HAS_GTTS = False

try:
    from PyQt6.QtTextToSpeech import QTextToSpeech as _QtTTS
    _HAS_QT_TTS = True
except Exception:
    _QtTTS = None
    _HAS_QT_TTS = False

# audio_player (QtMultimedia) – optional, init lazily
try:
    import audio_player as _audio_player
    _HAS_AUDIO = _audio_player.is_available()
except Exception:
    _audio_player = None
    _HAS_AUDIO = False

# --- constants ---
ENGINE_AUTO = "auto"
ENGINE_EDGE = "edge"
ENGINE_GTTS = "gtts"
_ALL_ENGINES = (ENGINE_AUTO, ENGINE_EDGE, ENGINE_GTTS)

EDGE_VOICES_CS = [
    ("cs-CZ-VlastaNeural", "Vlasta (žena) – Edge"),
    ("cs-CZ-AntoninNeural", "Antonín (muž) – Edge"),
]
DEFAULT_EDGE_VOICE = "cs-CZ-VlastaNeural"
DEFAULT_GTTS_LANG = "cs"

# --- state ---
_speaker = None
_enabled = True
_engine = ENGINE_AUTO
_edge_voice = DEFAULT_EDGE_VOICE
_gtts_lang = DEFAULT_GTTS_LANG
_fallback_cb = None  # fn(msg)
_queue: queue.Queue = queue.Queue()
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()
_last_tmp_files: list[str] = []


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


def _speak_auto_sync(text: str, interrupt: bool = False) -> bool:
    """Synchronní offline řeč. Vrací True pokud se povedlo."""
    txt = str(text).strip() if text else ""
    if not txt:
        return False
    spk = _get_speaker()
    if spk is not None:
        try:
            try:
                spk.speak(txt, interrupt=interrupt)
            except TypeError:
                spk.speak(txt)
            return True
        except Exception:
            pass
    # fallback Qt TTS
    if _HAS_QT_TTS and _QtTTS is not None:
        try:
            eng = _QtTTS()
            try:
                # prefer cs-CZ if available
                from PyQt6.QtCore import QLocale
                eng.setLocale(QLocale("cs_CZ"))
            except Exception:
                pass
            eng.say(txt)
            return True
        except Exception:
            pass
    return False


def _fetch_edge(text: str) -> str | None:
    """Stáhne mp3 přes edge-tts, vrátí cestu nebo None. Timeout ~8s."""
    if not _HAS_EDGE:
        return None
    txt = str(text).strip()
    if not txt:
        return None
    tmp = None
    try:
        f = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3", dir=tempfile.gettempdir(), prefix="pc_editor_tts_edge_")
        tmp = f.name
        f.close()
        # edge-tts async save with timeout
        import asyncio
        from edge_tts import Communicate

        voice = _edge_voice or DEFAULT_EDGE_VOICE

        async def _save():
            comm = Communicate(txt, voice)
            await comm.save(tmp)

        # run with timeout
        async def _save_with_timeout():
            try:
                await asyncio.wait_for(_save(), timeout=8.0)
            except asyncio.TimeoutError:
                raise TimeoutError("edge-tts timeout")

        # new loop in this thread (worker thread has no loop)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_save_with_timeout())
        finally:
            try:
                loop.close()
            except Exception:
                pass
            try:
                asyncio.set_event_loop(None)
            except Exception:
                pass

        if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
            return tmp
        try:
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)
        except Exception:
            pass
        return None
    except Exception as e:
        # print(f"[tts edge] {e}", file=sys.stderr)
        if tmp and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except Exception:
                pass
        return None


def _fetch_gtts(text: str) -> str | None:
    if not _HAS_GTTS:
        return None
    txt = str(text).strip()
    if not txt:
        return None
    tmp = None
    try:
        f = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3", dir=tempfile.gettempdir(), prefix="pc_editor_tts_gtts_")
        tmp = f.name
        f.close()
        from gtts import gTTS

        # gTTS can hang; run with thread timeout via concurrent
        import concurrent.futures

        def _do_save():
            tts = gTTS(text=txt, lang=_gtts_lang or "cs", slow=False)
            tts.save(tmp)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(_do_save)
            try:
                fut.result(timeout=8.0)
            except concurrent.futures.TimeoutError:
                return None

        if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
            return tmp
        try:
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)
        except Exception:
            pass
        return None
    except Exception:
        if tmp and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except Exception:
                pass
        return None


def _schedule_play(path: str) -> bool:
    """Naplánuje přehrání mp3 přes audio_player bridge. Vrací True pokud naplánováno."""
    if not path or not os.path.exists(path):
        return False
    if _audio_player is not None:
        try:
            ok = _audio_player.play_mp3(path)
            if ok:
                _last_tmp_files.append(path)
                # keep only last 5 paths for cleanup fallback
                if len(_last_tmp_files) > 5:
                    old = _last_tmp_files.pop(0)
                    try:
                        if os.path.exists(old) and old != path:
                            # don't delete if still playing; audio_player handles it
                            pass
                    except Exception:
                        pass
                return True
        except Exception:
            pass
    # if no audio player, cannot play online mp3 – fallback
    try:
        if os.path.exists(path):
            os.unlink(path)
    except Exception:
        pass
    return False


def _clear_queue():
    try:
        while not _queue.empty():
            try:
                _queue.get_nowait()
                _queue.task_done()
            except Exception:
                break
    except Exception:
        pass


def _notify_fallback(msg: str):
    cb = _fallback_cb
    if cb is not None:
        try:
            cb(msg)
        except Exception:
            pass


def _worker_loop():
    while True:
        try:
            item = _queue.get()
            if item is None:
                _queue.task_done()
                break
            text, interrupt = item
            if interrupt:
                # stop current audio
                if _audio_player is not None:
                    try:
                        _audio_player.stop()
                    except Exception:
                        pass
                _clear_queue()
                # also stop auto speaker if possible (no API, ignore)

            if not _enabled or not text:
                _queue.task_done()
                continue

            txt = str(text).strip()
            if not txt:
                _queue.task_done()
                continue

            eng = _engine

            if eng == ENGINE_AUTO:
                _speak_auto_sync(txt, interrupt=interrupt)
            elif eng == ENGINE_EDGE:
                if not _HAS_EDGE:
                    _speak_auto_sync(txt, interrupt=interrupt)
                    _notify_fallback("Edge TTS není nainstalován. Použit offline hlas.")
                elif not _HAS_AUDIO:
                    _speak_auto_sync(txt, interrupt=interrupt)
                    _notify_fallback("QtMultimedia není dostupné. Použit offline hlas.")
                else:
                    path = _fetch_edge(txt)
                    if path and os.path.exists(path):
                        ok = _schedule_play(path)
                        if not ok:
                            _speak_auto_sync(txt, interrupt=interrupt)
                    else:
                        _speak_auto_sync(txt, interrupt=interrupt)
                        _notify_fallback("Hlas online selhal (zkontrolujte internet). Použit offline hlas.")
            elif eng == ENGINE_GTTS:
                if not _HAS_GTTS:
                    _speak_auto_sync(txt, interrupt=interrupt)
                    _notify_fallback("gTTS není nainstalován. Použit offline hlas.")
                elif not _HAS_AUDIO:
                    _speak_auto_sync(txt, interrupt=interrupt)
                    _notify_fallback("QtMultimedia není dostupné. Použit offline hlas.")
                else:
                    path = _fetch_gtts(txt)
                    if path and os.path.exists(path):
                        ok = _schedule_play(path)
                        if not ok:
                            _speak_auto_sync(txt, interrupt=interrupt)
                    else:
                        _speak_auto_sync(txt, interrupt=interrupt)
                        _notify_fallback("Hlas online selhal (zkontrolujte internet). Použit offline hlas.")
            else:
                _speak_auto_sync(txt, interrupt=interrupt)

            _queue.task_done()
        except Exception:
            try:
                _queue.task_done()
            except Exception:
                pass
            # traceback.print_exc()


def _ensure_worker():
    global _worker
    with _worker_lock:
        if _worker is not None and _worker.is_alive():
            return
        # daemon so app can exit
        _worker = threading.Thread(target=_worker_loop, daemon=True, name="tts-worker")
        _worker.start()


def _ensure_audio_bridge():
    if _audio_player is None:
        return
    try:
        # must be called from main thread after QApplication
        _audio_player.init_bridge()
    except Exception:
        pass


# --- public API ---

def set_fallback_callback(fn):
    """Nastaví callback(msg) volaný při fallbacku online->offline (pro statusBar)."""
    global _fallback_cb
    _fallback_cb = fn


def set_enabled(enabled: bool):
    global _enabled
    _enabled = bool(enabled)


def is_enabled() -> bool:
    return bool(_enabled)


def set_engine(name: str):
    global _engine
    n = str(name or "").strip().lower()
    if n not in _ALL_ENGINES:
        n = ENGINE_AUTO
    _engine = n
    # ensure worker and audio bridge ready for online engines
    if n in (ENGINE_EDGE, ENGINE_GTTS):
        _ensure_audio_bridge()
        _ensure_worker()


def get_engine() -> str:
    return _engine


def set_edge_voice(voice: str):
    global _edge_voice
    v = str(voice or "").strip()
    if not v:
        return
    # basic validation: must be like cs-CZ-...Neural
    _edge_voice = v


def get_edge_voice() -> str:
    return _edge_voice or DEFAULT_EDGE_VOICE


def set_gtts_lang(lang: str):
    global _gtts_lang
    _gtts_lang = str(lang or "cs").strip() or "cs"


def get_available_engines():
    """
    Vrací list[(id, label, available, reason)] pro UI.
    """
    res = []
    # auto always available (accessible_output2 or QtTTS)
    res.append((ENGINE_AUTO, "Čtečka obrazovky (offline)", True, "" if (_HAS_AO2 or _HAS_QT_TTS) else "Není accessible_output2 ani QtTTS"))
    # edge
    if _HAS_EDGE and _HAS_AUDIO:
        res.append((ENGINE_EDGE, "Edge TTS – kvalitní (online)", True, ""))
    elif not _HAS_EDGE:
        res.append((ENGINE_EDGE, "Edge TTS – kvalitní (online)", False, "Nainstalujte: pip install edge-tts"))
    elif not _HAS_AUDIO:
        res.append((ENGINE_EDGE, "Edge TTS – kvalitní (online)", False, "QtMultimedia není dostupné"))
    # gtts
    if _HAS_GTTS and _HAS_AUDIO:
        res.append((ENGINE_GTTS, "Google gTTS (online)", True, ""))
    elif not _HAS_GTTS:
        res.append((ENGINE_GTTS, "Google gTTS (online)", False, "Nainstalujte: pip install gTTS"))
    else:
        res.append((ENGINE_GTTS, "Google gTTS (online)", False, "QtMultimedia není dostupné"))
    return res


def is_available(engine: str) -> bool:
    for eid, _, avail, _ in get_available_engines():
        if eid == engine:
            return bool(avail)
    return False


def stop():
    """Přeruší aktuální promluvu a vyprázdní frontu."""
    _clear_queue()
    if _audio_player is not None:
        try:
            _audio_player.stop()
        except Exception:
            pass
    # drain queue again
    _clear_queue()


def speak(text: str, interrupt: bool = False):
    """Zařadí text do fronty. Tiché selhání. Neváže UI vlákno."""
    if not _enabled or not text:
        return
    txt = str(text).strip()
    if not txt:
        return
    if interrupt:
        stop()
    # ensure bridge and worker are ready (bridge must be in main thread, so try)
    if _engine in (ENGINE_EDGE, ENGINE_GTTS):
        _ensure_audio_bridge()
    _ensure_worker()
    try:
        _queue.put_nowait((txt, bool(interrupt)))
    except Exception:
        # fallback sync
        _speak_auto_sync(txt, interrupt=interrupt)


def init_after_app():
    """Volat po QApplication pro přípravu audio bridge."""
    _ensure_audio_bridge()
    _ensure_worker()
