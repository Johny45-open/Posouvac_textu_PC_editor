"""
QtMultimedia přehrávač pro online TTS (edge-tts, gTTS).
Musí běžet v hlavním Qt vlákně – proto bridge s QueuedConnection.
Fallback: pokud QtMultimedia není, vrátí False a volající použije accessible_output2.
"""
import os

_BRIDGE = None
_HAS_QT = None

try:
    from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput  # type: ignore
    from PyQt6.QtCore import QObject, pyqtSignal, QUrl, QTimer
    _HAS_QT = True
except Exception:
    _HAS_QT = False
    QMediaPlayer = None  # type: ignore
    QAudioOutput = None  # type: ignore
    QObject = object  # type: ignore
    pyqtSignal = lambda *a, **kw: None  # type: ignore


if _HAS_QT:
    class _Bridge(QObject):
        playRequested = pyqtSignal(str)
        stopRequested = pyqtSignal()

        def __init__(self):
            super().__init__()
            self._player = None
            self._audio = None
            self._pending_cleanup = []
            self.playRequested.connect(self._on_play)
            self.stopRequested.connect(self._on_stop)

        def _ensure(self):
            if self._player is not None:
                return self._player
            try:
                self._player = QMediaPlayer()
                self._audio = QAudioOutput()
                self._player.setAudioOutput(self._audio)
                # cleanup temp file after playback finishes
                try:
                    self._player.playbackStateChanged.connect(self._on_state)
                    self._player.mediaStatusChanged.connect(self._on_status)
                except Exception:
                    pass
                return self._player
            except Exception:
                return None

        def _on_play(self, path: str):
            p = self._ensure()
            if p is None:
                return
            try:
                # Qt6: setSource expects QUrl
                p.stop()
                p.setSource(QUrl.fromLocalFile(path))
                # modest volume
                try:
                    if self._audio is not None:
                        self._audio.setVolume(0.9)
                except Exception:
                    pass
                p.play()
                # schedule temp file cleanup after ~20s (max utterance)
                try:
                    QTimer.singleShot(20000, lambda pp=path: self._cleanup(pp))
                except Exception:
                    pass
            except Exception:
                pass

        def _on_stop(self):
            try:
                if self._player is not None:
                    self._player.stop()
            except Exception:
                pass

        def _on_state(self, state):
            # state 0=Stopped
            pass

        def _on_status(self, status):
            pass

        def _cleanup(self, path: str):
            try:
                if os.path.exists(path):
                    # don't delete while still playing same file
                    try:
                        cur = self._player.source().toLocalFile() if self._player else ""
                        if cur and os.path.abspath(cur) == os.path.abspath(path):
                            # still playing, retry later
                            QTimer.singleShot(5000, lambda: self._cleanup(path))
                            return
                    except Exception:
                        pass
                    os.unlink(path)
            except Exception:
                pass


def is_available() -> bool:
    """True pokud QtMultimedia lze použít."""
    return bool(_HAS_QT)


def init_bridge():
    """Vytvořit bridge v hlavním vlákně. Volat po QApplication."""
    global _BRIDGE
    if not _HAS_QT:
        return None
    if _BRIDGE is not None:
        return _BRIDGE
    try:
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import QThread
        app = QApplication.instance()
        _BRIDGE = _Bridge()
        if app is not None:
            try:
                # ensure bridge lives in main thread
                if QThread.currentThread() != app.thread():
                    _BRIDGE.moveToThread(app.thread())
            except Exception:
                pass
        return _BRIDGE
    except Exception:
        return None


def get_bridge():
    global _BRIDGE
    if _BRIDGE is not None:
        return _BRIDGE
    return init_bridge()


def play_mp3(path: str) -> bool:
    """Naplánuje přehrání v main threadu (queued). Vrací True pokud naplánováno."""
    if not _HAS_QT or not path or not os.path.exists(path):
        return False
    br = get_bridge()
    if br is None:
        return False
    try:
        # Queued emit – pokud voláno z worker threadu, dorazí do main threadu
        br.playRequested.emit(path)
        return True
    except Exception:
        try:
            br._on_play(path)
            return True
        except Exception:
            return False


def stop():
    if not _HAS_QT:
        return
    br = get_bridge()
    if br is None:
        return
    try:
        br.stopRequested.emit()
    except Exception:
        try:
            br._on_stop()
        except Exception:
            pass
