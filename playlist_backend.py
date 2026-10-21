import json
import re
import csv
import io
import html
import uuid
from datetime import datetime, timezone

MAX_QR_LENGTH = 1500

# --- Identita setlistu a výskytů (JSON v5, etapa A1.1) ---
# Verze zapisovaná novými klienty. Čtení v3/v4 zůstává zachováno – parser
# číslo verze nekontroluje, čte klíče opportunisticky (stejně jako telefon).
PLAYLIST_JSON_VERSION = 5

# Kanonická pole horní úrovně JSON (kontrakt v5).
TOP_LEVEL_KNOWN_FIELDS = {
    "type", "version", "name", "exportedAt", "totalDuration", "unknownCount",
    "songs", "ttsEngine", "ttsVoice", "playlistUid",
}
# Interní klíče načítací vrstvy – nikdy se neexportují jako data souboru.
TOP_LEVEL_INTERNAL_FIELDS = {"_normSongs", "_extras"}

# Kanonická pole položky setlistu. Cokoli jiného patří do "extras"
# a musí se při exportu zachovat (rozhodnutí č. 6 schválení A1.1).
SONG_KNOWN_FIELDS = {
    "title", "name", "artist", "duration", "tempo", "content",
    "stopMarks", "stop_marks", "filePath", "occurrenceId",
    "scrollSpeed", "fontSize", "introDuration", "stopMarksOverride", "extras",
}

# Port lib/main.dart:70 parseImportedFileName – Interpret - Název
_SEPARATOR_RE = re.compile(r'\s+[-–—]\s+')
_SEPARATOR_LOOSE_RE = re.compile(r'\s*[-–—]\s*')


def parse_song_input(raw: str):
    """Rozdělí 'Interpret - Název' na (artist, title). Port lib/main.dart:70."""
    s = (raw or "").strip()
    if not s:
        return ("", "")
    # preferuj " - " s mezerami, jinak poslední výskyt pomlčky
    m = _SEPARATOR_RE.search(s)
    if m is None:
        all_m = list(_SEPARATOR_LOOSE_RE.finditer(s))
        if all_m:
            m = all_m[-1]
    if m is None:
        return ("", s)
    artist = s[:m.start()].strip()
    title = s[m.end():].strip()
    if not artist or not title:
        return ("", s)
    return (artist, title)


def parse_duration(raw: str):
    """'3:30' / '3:05' / '210' / '3m30s' -> sekundy int nebo None. Prázdné -> None."""
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if not s:
        return None
    # "3:30" nebo "03:05"
    if ":" in s:
        parts = s.split(":")
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            m = int(parts[0]); sec = int(parts[1])
            if 0 <= sec < 60 and m >= 0:
                total = m * 60 + sec
                return total if total > 0 else None
        return None
    # "3m30s" / "3m" / "30s"
    m_match = re.match(r'^\s*(\d+)\s*m\s*(\d+)?\s*s?\s*$', s)
    if m_match:
        m = int(m_match.group(1))
        sec = int(m_match.group(2)) if m_match.group(2) else 0
        if 0 <= sec < 60:
            total = m * 60 + sec
            return total if total > 0 else None
    # čisté sekundy
    if s.isdigit():
        v = int(s)
        return v if v > 0 else None
    # float jako sekundy? ne
    return None


def format_duration(seconds):
    if seconds is None or seconds <= 0:
        return "?"
    try:
        sec = int(seconds)
    except Exception:
        return "?"
    m = sec // 60
    s = sec % 60
    return f"{m}:{s:02d}"


def parse_tempo(raw: str):
    """String/num -> float 30-300 nebo None."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        v = float(s.replace(",", "."))
    except Exception:
        return None
    if 30 <= v <= 300:
        return float(v)
    return None


def new_playlist_uid() -> str:
    """Nové přenosové ID setlistu (UUIDv4). Generuje se při vzniku setlistu,
    nikdy při každém exportu."""
    return str(uuid.uuid4())


def new_occurrence_id() -> str:
    """Nové přenosové ID výskytu písně (UUIDv4). Generuje se při vzniku výskytu
    (přidání do setlistu, kopie), nikdy při exportu ani při přesunu/úpravě."""
    return str(uuid.uuid4())


def _valid_uid(value) -> str | None:
    """Neprůhledný přenosový identifikátor musí být neprázdný řetězec."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def ensure_song_ids(songs: list) -> list:
    """Doplní chybějící occurrenceId a ošetří kolize uvnitř seznamu (in-place).

    - Staré soubory bez ID: doplní se jednou a zůstanou uložené v položce,
      takže při dalším uložení přežijí (pravidlo schválení A1.1).
    - Kolize dvou stejných ID v jednom seznamu = nebezpečí sloučení cizích
      položek při importu → druhý výskyt dostane ID nové.
    - Položky, které nejsou dict, se nechají být (řetězce normalizuje jinde).
    Nikdy se nepřepočítává ID, které je v seznamu jediné a platné.
    """
    seen: set[str] = set()
    for item in songs or []:
        if not isinstance(item, dict):
            continue
        uid = _valid_uid(item.get("occurrenceId"))
        if uid is None or uid in seen:
            uid = new_occurrence_id()
            item["occurrenceId"] = uid
        seen.add(uid)
    return songs


def clone_songs(songs: list) -> list:
    """Hluboká kopie položek setlistu s NOVÝMI occurrenceId.
    Kopie setlistu nesmí sdílet identitu s originálem."""
    out = []
    for item in songs or []:
        if isinstance(item, dict):
            copy = json.loads(json.dumps(item, ensure_ascii=False))
            copy["occurrenceId"] = new_occurrence_id()
            out.append(copy)
        else:
            out.append(item)
    return out


def clone_setlist(songs: list) -> tuple[str, list]:
    """Vytvoří kopii setlistu: (nové playlistUid, položky s novými occurrenceId)."""
    return new_playlist_uid(), clone_songs(songs)


def _field_signature(value) -> str:
    """Porovnávací otisk hodnoty pole (pro zjištění odlišného nastavení výskytů)."""
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        return str(value)


def legacy_export_warnings(songs: list) -> list[str]:
    """Varování před exportem pro starší aplikace (neznají occurrenceId / JSON v5).

    Starší telefonní aplikace vkládají položky přes INSERT OR IGNORE nad
    kompozitním klíčem (playlistId, songId) – opakovanou skladbu tiše sloučí
    a přijdou tak o její odlišné nastavení (tempo, zarážky atd.).
    """
    def norm(s): return re.sub(r'\s+', ' ', (s or "").strip().lower())
    groups: dict[str, list[dict]] = {}
    for s in songs or []:
        if not isinstance(s, dict):
            continue
        key = f"{norm(s.get('artist'))}|{norm(s.get('title'))}"
        groups.setdefault(key, []).append(s)
    warnings: list[str] = []
    sig_fields = ("tempo", "duration", "scrollSpeed", "introDuration",
                  "stopMarks", "stopMarksOverride")
    for key, items in groups.items():
        if len(items) < 2 or not key.strip("|"):
            continue
        label = f"{items[0].get('artist')} – {items[0].get('title')}"
        distinct = any(
            _field_signature(items[0].get(f)) != _field_signature(other.get(f))
            for other in items[1:]
            for f in sig_fields
        )
        if distinct:
            warnings.append(
                f"„{label}“ je v setlistu {len(items)}× s odlišným nastavením – "
                f"starší aplikace výskyty sloučí a odlišné nastavení ztratí."
            )
        else:
            warnings.append(
                f"„{label}“ je v setlistu {len(items)}× – starší aplikace "
                f"zobrazí jen jeden výskyt."
            )
    return warnings


def _preserve_number(value):
    """Zachová hodnotu nastavení (scrollSpeed/fontSize/introDuration).

    Číselný řetězec se převede na float, číslo zůstane číslem a cokoli jiného
    se ponechá doslova – pole se NESMÍ ztratit jen proto, že ho editor
    zatím neumí zpracovat (rozhodnutí č. 7 schválení A1.1).
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        s = value.strip().replace(",", ".")
        if s:
            try:
                return float(s)
            except ValueError:
                return value
        return None
    return value


def _normalize_song_entry(entry):
    """Normalizuje položku songs na dict {title,artist,duration,tempo,stopMarks,content,filePath} pro UI."""
    if isinstance(entry, dict):
        title = str(entry.get("title") or entry.get("name") or "").strip()
        artist = str(entry.get("artist") or "").strip()
        if not title and not artist:
            return None
        # když title obsahuje pomlčku a artist prázdný, zkus parse
        if not artist and title and " - " in title:
            a, t = parse_song_input(title)
            if a and t:
                artist, title = a, t
        dur = entry.get("duration")
        if isinstance(dur, str):
            dur = parse_duration(dur)
        elif isinstance(dur, (int, float)):
            dur = int(dur) if int(dur) > 0 else None
        else:
            dur = None
        tempo = parse_tempo(entry.get("tempo"))
        # stopMarks: list[{lineText,lineIndex,bars}] – zachovat
        raw_marks = entry.get("stopMarks") or entry.get("stop_marks") or []
        stop_marks = []
        if isinstance(raw_marks, list):
            for m in raw_marks:
                if not isinstance(m, dict):
                    continue
                bars = m.get("bars") if m.get("bars") is not None else m.get("durationBars")
                try:
                    bars = int(bars) if bars is not None else None
                except Exception:
                    bars = None
                if bars is None or bars <= 0:
                    continue
                bars = max(1, min(16, bars))
                line_text = str(m.get("lineText") or m.get("line_text") or m.get("line") or "").strip()
                # lineIndex volitelný
                try:
                    idx = int(m.get("lineIndex")) if m.get("lineIndex") is not None else None
                except Exception:
                    idx = None
                stop_marks.append({"lineText": line_text, "lineIndex": idx, "bars": bars})
        # --- Zachování identity a nastavení (etapa A1.1) ---
        occurrence_id = _valid_uid(entry.get("occurrenceId"))
        scroll_speed = _preserve_number(entry.get("scrollSpeed"))
        font_size = _preserve_number(entry.get("fontSize"))
        intro_duration = _preserve_number(entry.get("introDuration"))
        stop_override = entry.get("stopMarksOverride")
        # Neznámá pole → extras; kanonická (známá) pole mají vždy přednost,
        # proto se ze extras odstraní (rozhodnutí č. 6 schválení A1.1).
        extras: dict = {}
        raw_extras = entry.get("extras")
        if isinstance(raw_extras, dict):
            extras.update(raw_extras)
        for k, v in entry.items():
            if k not in SONG_KNOWN_FIELDS:
                extras[k] = v
        extras = {k: v for k, v in extras.items() if k not in SONG_KNOWN_FIELDS}
        result = {"title": title, "artist": artist, "duration": dur, "tempo": tempo, "content": entry.get("content"), "stopMarks": stop_marks}
        # filePath pro PC editor (interní)
        if entry.get("filePath"):
            result["filePath"] = str(entry.get("filePath"))
        if occurrence_id:
            result["occurrenceId"] = occurrence_id
        if scroll_speed is not None:
            result["scrollSpeed"] = scroll_speed
        if font_size is not None:
            result["fontSize"] = font_size
        if intro_duration is not None:
            result["introDuration"] = intro_duration
        if stop_override is not None:
            result["stopMarksOverride"] = stop_override
        if extras:
            result["extras"] = extras
        return result
    else:
        raw = str(entry).strip()
        if not raw:
            return None
        a, t = parse_song_input(raw)
        if not a:
            return {"title": raw, "artist": "", "duration": None, "tempo": None}
        return {"title": t, "artist": a, "duration": None, "tempo": None}


def build_playlist_data(name, songs, tts_engine=None, tts_voice=None,
                        playlist_uid=None, top_extras=None):
    """Sestaví v5 playlist dict (zpětně kompatibilní s v2/v3/v4 při čtení).

    tts_engine/tts_voice se ukládá jako meta pro per-setlist preferenci hlasu.
    playlist_uid – přenosové ID setlistu (playlistUid); generuje se při vzniku
    setlistu, sem se jen přenáší.
    top_extras – neznámá pole z načteného souboru, která se mají zachovat.
    Kanonická pole mají přednost, proto se extras přidávají až nakonec."""
    if not name or not (isinstance(name, str) and name.strip()):
        return None
    if not songs:
        return None
    clean = []
    total = 0
    unknown = 0
    for s in songs:
        norm = _normalize_song_entry(s)
        if norm is None or not norm.get("title"):
            continue
        entry = {"title": norm["title"], "artist": norm["artist"]}
        if norm.get("duration") is not None and norm["duration"] > 0:
            entry["duration"] = int(norm["duration"])
            total += int(norm["duration"])
        else:
            entry["duration"] = None
            unknown += 1
        if norm.get("tempo") is not None:
            entry["tempo"] = float(norm["tempo"])
        # content pouze pokud existuje a není prázdné (pro balík s texty)
        if norm.get("content"):
            c = str(norm["content"]).strip()
            if c:
                entry["content"] = c
        # stopMarks – v3+ (lineIndex v čistém prostoru, B1)
        marks = norm.get("stopMarks") or []
        if marks:
            entry["stopMarks"] = [{"lineText": m["lineText"], "lineIndex": m.get("lineIndex"), "bars": int(m["bars"])} for m in marks]
            # odstranit None lineIndex pro čistší JSON
            for mm in entry["stopMarks"]:
                if mm["lineIndex"] is None:
                    del mm["lineIndex"]
        # filePath se neexportuje (interní)
        if entry["duration"] is None:
            del entry["duration"]
        if "tempo" in entry and entry["tempo"] is None:
            del entry["tempo"]
        # identita výskytu + nastavení, která editor jen zachovává (A1.1)
        if norm.get("occurrenceId"):
            entry["occurrenceId"] = norm["occurrenceId"]
        for key in ("scrollSpeed", "fontSize", "introDuration"):
            if norm.get(key) is not None:
                entry[key] = norm[key]
        if norm.get("stopMarksOverride") is not None:
            entry["stopMarksOverride"] = norm["stopMarksOverride"]
        # neznámá pole položky – až po kanonických, nesmí je přepsat
        for k, v in (norm.get("extras") or {}).items():
            if k not in entry and not str(k).startswith("_"):
                entry[k] = v
        clean.append(entry)
    if not clean:
        return None
    data = {
        "type": "playlist",
        "version": PLAYLIST_JSON_VERSION,
        "name": name.strip(),
        "exportedAt": datetime.now(timezone.utc).isoformat(),
        "totalDuration": total,
        "unknownCount": unknown,
        "songs": clean,
    }
    uid = _valid_uid(playlist_uid)
    if uid:
        data["playlistUid"] = uid
    # per-setlist TTS preference (obojí: QSettings + JSON)
    if tts_engine and str(tts_engine).strip().lower() in ("auto", "edge", "gtts"):
        data["ttsEngine"] = str(tts_engine).strip().lower()
        if tts_voice:
            data["ttsVoice"] = str(tts_voice).strip()
    # neznámá pole horní úrovně – až úplně nakonec (kanonická pole vyhrávají)
    if isinstance(top_extras, dict):
        for k, v in top_extras.items():
            if k not in data and not str(k).startswith("_"):
                data[k] = v
    return data


def playlist_to_text(name, songs, tts_engine=None, tts_voice=None,
                     playlist_uid=None, top_extras=None):
    data = build_playlist_data(name, songs, tts_engine=tts_engine, tts_voice=tts_voice,
                               playlist_uid=playlist_uid, top_extras=top_extras)
    if data is None:
        return None
    return json.dumps(data, ensure_ascii=False, indent=2)


def save_playlist(name, songs, tts_engine=None, tts_voice=None,
                  playlist_uid=None, top_extras=None):
    filename = f"{name.strip().replace(' ', '_')}.json"
    return save_playlist_to(filename, name, songs, tts_engine=tts_engine, tts_voice=tts_voice,
                            playlist_uid=playlist_uid, top_extras=top_extras)


def save_playlist_to(filename, name, songs, tts_engine=None, tts_voice=None,
                     playlist_uid=None, top_extras=None):
    if not name or not str(name).strip() or not songs:
        return False, "Název ani seznam písní nesmí být prázdný."
    data = build_playlist_data(name, songs, tts_engine=tts_engine, tts_voice=tts_voice,
                               playlist_uid=playlist_uid, top_extras=top_extras)
    if data is None:
        return False, "Nepodařilo se sestavit playlist (prázdné položky)."
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True, filename
    except Exception as e:
        return False, str(e)


def load_playlist(filename):
    try:
        with open(filename, 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
        # normalizovat pro UI – ale vrátit raw data pro zpětnou kompatibilitu
        if isinstance(data, dict) and "songs" in data:
            # neznámá pole horní úrovně zachovat pro zpětný export (A1.1)
            extras = {k: v for k, v in data.items()
                      if k not in TOP_LEVEL_KNOWN_FIELDS and k not in TOP_LEVEL_INTERNAL_FIELDS}
            if extras:
                data["_extras"] = extras
            raw_songs = data.get("songs")
            if not isinstance(raw_songs, list):
                raw_songs = []
            norm_songs = []
            pairs: list[tuple] = []
            for s in raw_songs:
                n = _normalize_song_entry(s)
                if n and n.get("title"):
                    norm_songs.append(n)
                    pairs.append((s, n))
            # Staré soubory bez ID: occurrenceId doplnit JEDNOU a zapsat zpět
            # do položek, aby při dalším uložení přežila (pravidlo A1.1).
            ensure_song_ids(norm_songs)
            for s, n in pairs:
                if isinstance(s, dict) and n.get("occurrenceId"):
                    s["occurrenceId"] = n["occurrenceId"]
            # vrátit obohacené data s norm_songs pod klíčem _normSongs,
            # původní songs zůstávají pro uložení/zpětnou kompatibilitu
            data["_normSongs"] = norm_songs
        return True, data
    except Exception as e:
        return False, str(e)


# --- CSV knihovna (autocomplete) ---

def _parse_csv_line(line: str):
    """Respektuje čárky uvnitř uvozovek. Port lib/database.dart:371."""
    # zkus csv modul s dialekty
    for delim in [',', ';']:
        try:
            reader = csv.reader(io.StringIO(line), delimiter=delim, quotechar='"', doublequote=True, skipinitialspace=True)
            parts = next(reader)
            # heuristika: pokud je aspoň 2 sloupce a hlavička obsahuje artist/title/id, bereme
            if len(parts) >= 2:
                # rychlý test: pokud delim==',' a máme 5 sloupců nebo aspoň 2, vrať
                # pokud delim==';' a čárková verze měla 1 sloupec, použij středník
                # jednoduché: zkus čárku, pokud 1 sloupec a je tam středník, zkus středník
                if delim == ',' and len(parts) == 1 and ';' in line:
                    continue
                return [p.strip().strip('"').strip() for p in parts]
        except Exception:
            continue
    # fallback split
    return [p.strip().strip('"') for p in line.split(',')]


def load_csv_library(filename):
    """Načte metadata_pisni.csv (id,artist,title,duration,filePath) pro autocomplete.
       Vrací (True, list[dict]) nebo (False, err_str)."""
    try:
        with open(filename, 'r', encoding='utf-8-sig') as f:
            content = f.read()
        lines = content.splitlines()
        if not lines:
            return False, "Prázdný soubor."
        header = _parse_csv_line(lines[0])
        # map indexů – case-insensitive
        lower = [h.lower() for h in header]
        try:
            artist_idx = lower.index("artist")
        except ValueError:
            artist_idx = 1 if len(header) > 1 else -1
        try:
            title_idx = lower.index("title")
        except ValueError:
            title_idx = 2 if len(header) > 2 else -1
        try:
            dur_idx = lower.index("duration")
        except ValueError:
            dur_idx = 3 if len(header) > 3 else -1
        result = []
        for line in lines[1:]:
            if not line.strip():
                continue
            parts = _parse_csv_line(line)
            if len(parts) <= max(artist_idx, title_idx):
                continue
            artist = parts[artist_idx].strip() if artist_idx >= 0 and artist_idx < len(parts) else ""
            title = parts[title_idx].strip() if title_idx >= 0 and title_idx < len(parts) else ""
            if not title:
                continue
            dur_raw = parts[dur_idx].strip() if dur_idx >= 0 and dur_idx < len(parts) else ""
            dur = parse_duration(dur_raw)
            # když CSV dává sekundy jako "210" nebo "0"
            if dur is None and dur_raw.isdigit():
                v = int(dur_raw)
                dur = v if v > 0 else None
            result.append({"artist": artist, "title": title, "duration": dur, "label": f"{artist} - {title}" if artist else title})
        return True, result
    except Exception as e:
        return False, str(e)


# --- HTML export ---

def build_playlist_html(name, songs, totalDuration=None, unknownCount=None):
    """Port lib/song_export.dart:119 buildPlaylistHtml."""
    # songs = list[dict]
    norm = []
    for s in songs:
        n = _normalize_song_entry(s)
        if n:
            norm.append(n)
    if totalDuration is None:
        totalDuration = sum(int(x["duration"]) for x in norm if x.get("duration"))
    if unknownCount is None:
        unknownCount = sum(1 for x in norm if not x.get("duration"))
    totalMin = (totalDuration or 0) // 60
    totalSec = (totalDuration or 0) % 60
    if unknownCount == 0:
        time_label = f"Celkový čas: {totalMin} min {totalSec:02d} s"
    else:
        time_label = f"Celkový čas: {totalMin} min {totalSec:02d} s + {unknownCount} bez času (odhad +{unknownCount*3} min)"
    esc = html.escape
    out = []
    out.append("<!DOCTYPE html>")
    out.append('<html lang="cs">')
    out.append("<head>")
    out.append('<meta charset="UTF-8">')
    out.append('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
    out.append(f"<title>{esc(name)} – setlist</title>")
    out.append("<style>")
    out.append("  body { font-family: sans-serif; font-size: 18px; line-height: 1.5; margin: 16px; color: #111; }")
    out.append("  h1 { font-size: 28px; margin-bottom: 4px; }")
    out.append("  .meta { color: #555; margin-bottom: 16px; }")
    out.append("  table { width: 100%; border-collapse: collapse; }")
    out.append("  th, td { text-align: left; padding: 8px; border-bottom: 1px solid #ddd; }")
    out.append("  th { background: #f0f0f0; }")
    out.append("  .dur { text-align: right; white-space: nowrap; }")
    out.append("  .unknown { color: #c62828; }")
    out.append("</style>")
    out.append("</head>")
    out.append("<body>")
    out.append("<main>")
    out.append(f"<h1>{esc(name)}</h1>")
    out.append(f'<p class="meta">{esc(time_label)} • {len(norm)} písní</p>')
    out.append("<table>")
    out.append(f"<caption>Seznam písní v setlistu {esc(name)}</caption>")
    out.append('<thead><tr><th scope="col">#</th><th scope="col">Interpret</th><th scope="col">Název</th><th scope="col" class="dur">Délka</th><th scope="col" class="dur">Tempo</th></tr></thead>')
    out.append("<tbody>")
    for i, s in enumerate(norm):
        artist = esc(s.get("artist") or "")
        title = esc(s.get("title") or "")
        dur = s.get("duration")
        if dur and int(dur) > 0:
            d = int(dur); dur_text = f"{d//60}:{d%60:02d}"
        else:
            dur_text = '<span class="unknown">?</span>'
        tempo = s.get("tempo")
        tempo_text = f"{int(round(float(tempo)))} BPM" if tempo else '<span class="unknown">—</span>'
        out.append(f"<tr><td>{i+1}</td><td>{artist}</td><td>{title}</td><td class=\"dur\">{dur_text}</td><td class=\"dur\">{tempo_text}</td></tr>")
    out.append("</tbody></table>")
    out.append("</main>")
    out.append("</body>")
    out.append("</html>")
    return "\n".join(out)


def save_playlist_html(filename, name, songs):
    data = build_playlist_data(name, songs)
    if data is None:
        return False, "Prázdný playlist."
    html_str = build_playlist_html(data["name"], data["songs"], data["totalDuration"], data["unknownCount"])
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(html_str)
        return True, filename
    except Exception as e:
        return False, str(e)


# --- Word export wrapper (volitelná závislost python-docx) ---
def save_playlist_docx(filename, name, songs, include_details=True, include_texts=False, highlight_stops=True):
    """Wrapper nad word_export.save_playlist_docx s guardem pro chybějící závislost."""
    try:
        import word_export
        return word_export.save_playlist_docx(
            filename, name, songs,
            include_details=include_details,
            include_texts=include_texts,
            highlight_stops=highlight_stops,
        )
    except ImportError as e:
        return False, f"Chybí python-docx ({e}). Nainstalujte: pip install python-docx"
    except Exception as e:
        return False, str(e)


def save_library_docx(filename, title, songs, include_duration=True, include_tempo=True, include_stops=True):
    """Wrapper nad word_export.save_library_docx."""
    try:
        import word_export
        return word_export.save_library_docx(
            filename, title, songs,
            include_duration=include_duration,
            include_tempo=include_tempo,
            include_stops=include_stops,
        )
    except ImportError as e:
        return False, f"Chybí python-docx ({e}). Nainstalujte: pip install python-docx"
    except Exception as e:
        return False, str(e)


def get_qr_payload(name, songs, playlist_uid=None, top_extras=None):
    """Vrátí JSON string pro QR (bez content/filePath) + délku.

    Formát je shodný s exportem JSON v5 – identita (playlistUid, occurrenceId),
    nastavení i neznámá pole se do QR NEvynechávají. Vynechává se jen
    `content` (záměrně, kvůli velikosti; telefon si text doplní z knihovny)
    a interní `filePath` (které se do JSONu stejně neexportuje).
    """
    data = build_playlist_data(name, songs, playlist_uid=playlist_uid, top_extras=top_extras)
    if data is None:
        return None, "Prázdný playlist."
    # očistit content pro QR (ostatní pole včetně ID a extras ponechat)
    clean_songs = []
    for s in data["songs"]:
        clean_songs.append({k: v for k, v in s.items() if k not in ("content", "filePath")})
    data["songs"] = clean_songs
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    # pretty pro schránku už dělá playlist_to_text; QR chce compact pro úsporu
    if len(payload) > MAX_QR_LENGTH:
        return None, (
            f"Setlist se nevejde do QR kódu ({len(payload)} znaků, limit {MAX_QR_LENGTH}). "
            f"Identifikační a nastavovací pole se do QR neskrývají – použijte "
            f"export JSON (Ctrl+J) nebo USB přenos."
        )
    return payload, None


# --- StopMarks helpers pro PC editor ---

def extract_stop_marks_from_content(content: str) -> list[dict]:
    """
    Z direktiv {stop:N}/{pause:N} v textu → [{lineText,lineIndex,bars}].

    lineIndex = index CÍLOVÉHO řádku v prostoru textu BEZ stop direktiv,
    lineText  = text tohoto cílového řádku (kontrolní kotva, nikoli způsob
    rozlišení opakovaných řádků).
    """
    try:
        import song_parser
    except Exception:
        return []
    phys = song_parser.split_physical_lines(content or "")
    clean_lines = [(p, kind, payload) for (p, kind, payload) in phys if kind in ("text", "comment")]
    marks: list[dict] = []
    clean_count = 0
    for p, kind, payload in phys:
        if kind == "stop":
            bars = song_parser.parse_directive_bars(payload)
            if bars <= 0:
                bars = 2
            # Cílový řádek = nejbližší následující čistý řádek.
            next_clean = next((c for c in clean_lines if c[0] > p), None)
            line_text_val = ""
            if next_clean is not None:
                line_text_val = song_parser.clean_line_text(next_clean[1], next_clean[2])
            marks.append({"lineText": line_text_val, "lineIndex": clean_count, "bars": int(bars)})
        elif kind in ("text", "comment"):
            clean_count += 1
    return marks


def _remove_all_stop_directives(content: str) -> str:
    """Odstraní všechny stop direktivy {stop:N}/{pause:N} (jako celé fyzické řádky)."""
    try:
        import song_parser
    except Exception:
        return content
    drop = {p for (p, kind, _pay) in song_parser.split_physical_lines(content) if kind == "stop"}
    raw_lines = song_parser.file_lines_raw(content)
    return "\n".join(raw for i, raw in enumerate(raw_lines) if i not in drop)


def file_content_with_stop_marks_applied(
    original_content: str,
    stop_marks: list[dict],
    errors: list | None = None,
) -> str:
    """
    Vezme původní obsah a seznam zarážek [{lineText,lineIndex,bars}] a vrátí obsah
    s vloženými direktivami {stop:N} před odpovídající řádky.

    lineIndex = index cílového řádku v prostoru BEZ stop direktiv (stejné významu
    jako v extract_stop_marks_from_content a insert_stop_directive).

    Postup: nejdřív odstraní všechny existující stop direktivy (jednotná čistá
    reprezentace), pak vloží požadované direktivy sestupně podle indexu, aby
    vkládání jedné zarážky neposouvalo cíl zarážek s nižším indexem.

    Pokud některou zarážku nelze spolehlivě umístit (neplatný index, neshoda
    lineIndex/lineText, nejednoznačný text bez indexu), operace se přeruší
    a vrátí se PŮVODNÍ obsah beze změny (žádná direktiva se nevloží ani
    neodstraní). Důvod se zapíše do volitelného seznamu errors.
    """
    try:
        import song_parser
    except Exception:
        return original_content

    def _fail(msg: str) -> str:
        if errors is not None:
            errors.append(msg)
        return original_content

    # 1) Jednotná čistá reprezentace – odstranit všechny stop direktivy.
    cleaned = _remove_all_stop_directives(original_content)

    # 2) Připravit zarážky v čistém indexovém prostoru.
    clean = [(p, kind, payload) for (p, kind, payload) in song_parser.split_physical_lines(cleaned)
             if kind in ("text", "comment")]

    prepared: list[tuple[int, int, str | None]] = []
    for m in (stop_marks or []):
        if not isinstance(m, dict):
            continue
        raw_bars = m.get("bars")
        if raw_bars is None:
            raw_bars = m.get("durationBars")
        try:
            bars = int(raw_bars) if raw_bars is not None else 2
        except Exception:
            bars = 2
        bars = max(1, min(16, bars))

        line_text_val = str(m.get("lineText") or m.get("line_text") or "").strip()
        raw_idx = m.get("lineIndex")
        if raw_idx is None:
            # Bez indexu lze cíl určit jen podle JEDNOZNAČNÉHO textu –
            # nikdy ne podle první textové shody.
            if not line_text_val:
                return _fail("Zarážka bez lineIndex i lineText – cíl nelze určit.")
            matches = [i for i, (_p, kind, payload) in enumerate(clean)
                       if song_parser.clean_line_text(kind, payload) == line_text_val]
            if len(matches) != 1:
                return _fail(
                    f"Zarážka bez lineIndex: text {line_text_val!r} není v textu "
                    f"jednoznačný ({len(matches)} shod) – cíl nelze určit."
                )
            idx = matches[0]
        else:
            try:
                idx = int(raw_idx)
            except Exception:
                return _fail(f"Zarážka s neplatným lineIndex {raw_idx!r}.")
        prepared.append((idx, bars, line_text_val or None))

    if not prepared:
        return cleaned

    # 3) Vložit sestupně podle cílového indexu (nižší indexy se neposunou).
    # lineText slouží jen jako kontrola cílového řádku, ne jako způsob výběru.
    result = cleaned
    for idx, bars, expected in sorted(prepared, key=lambda t: t[0], reverse=True):
        try:
            result = song_parser.insert_stop_directive(
                result, idx, bars, expected_line_text=expected,
            )
        except ValueError as e:
            return _fail(str(e))
    return result
