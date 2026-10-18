import json
import re
import csv
import io
import html
from datetime import datetime, timezone

MAX_QR_LENGTH = 1500

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
        result = {"title": title, "artist": artist, "duration": dur, "tempo": tempo, "content": entry.get("content"), "stopMarks": stop_marks}
        # filePath pro PC editor (interní)
        if entry.get("filePath"):
            result["filePath"] = str(entry.get("filePath"))
        return result
    else:
        raw = str(entry).strip()
        if not raw:
            return None
        a, t = parse_song_input(raw)
        if not a:
            return {"title": raw, "artist": "", "duration": None, "tempo": None}
        return {"title": t, "artist": a, "duration": None, "tempo": None}


def build_playlist_data(name, songs, tts_engine=None, tts_voice=None):
    """Sestaví v3 playlist dict (zpětně kompatibilní s v2). songs = list[dict|str] toleruje obojí.
       tts_engine/tts_voice se ukládá jako meta pro per-setlist preferenci hlasu (volitelné)."""
    if not name or not (isinstance(name, str) and name.strip()):
        return None
    if not songs:
        return None
    clean = []
    total = 0
    unknown = 0
    has_marks = False
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
        # stopMarks – v3
        marks = norm.get("stopMarks") or []
        if marks:
            has_marks = True
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
        clean.append(entry)
    if not clean:
        return None
    version = 3 if has_marks else 3  # vždy v3 pro PC editor (telefon umí v2 i v3)
    data = {
        "type": "playlist",
        "version": version,
        "name": name.strip(),
        "exportedAt": datetime.now(timezone.utc).isoformat(),
        "totalDuration": total,
        "unknownCount": unknown,
        "songs": clean,
    }
    # per-setlist TTS preference (obojí: QSettings + JSON)
    if tts_engine and str(tts_engine).strip().lower() in ("auto", "edge", "gtts"):
        data["ttsEngine"] = str(tts_engine).strip().lower()
        if tts_voice:
            data["ttsVoice"] = str(tts_voice).strip()
    return data


def playlist_to_text(name, songs, tts_engine=None, tts_voice=None):
    data = build_playlist_data(name, songs, tts_engine=tts_engine, tts_voice=tts_voice)
    if data is None:
        return None
    return json.dumps(data, ensure_ascii=False, indent=2)


def save_playlist(name, songs, tts_engine=None, tts_voice=None):
    filename = f"{name.strip().replace(' ', '_')}.json"
    return save_playlist_to(filename, name, songs, tts_engine=tts_engine, tts_voice=tts_voice)


def save_playlist_to(filename, name, songs, tts_engine=None, tts_voice=None):
    if not name or not str(name).strip() or not songs:
        return False, "Název ani seznam písní nesmí být prázdný."
    data = build_playlist_data(name, songs, tts_engine=tts_engine, tts_voice=tts_voice)
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
        # normalizovat na v2 pro UI – ale vrátit raw data pro zpětnou kompatibilitu
        # sjednocení: zajistit songs jako list[dict]
        if isinstance(data, dict) and "songs" in data:
            norm_songs = []
            for s in data.get("songs") or []:
                n = _normalize_song_entry(s)
                if n and n.get("title"):
                    norm_songs.append(n)
            # vrátit obohacené data s norm_songs pod klíčem _normSongs, ale zachovat původní songs pro uložení
            # pro GUI použijeme norm_songs
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


def get_qr_payload(name, songs):
    """Vrátí JSON string pro QR (bez content/filePath) + délku. Pro QR se používá stejné v3."""
    data = build_playlist_data(name, songs)
    if data is None:
        return None, "Prázdný playlist."
    # očistit content/filePath pro QR (stopMarks ponechat – malá velikost, užitečné)
    clean_songs = []
    for s in data["songs"]:
        clean_songs.append({k: v for k, v in s.items() if k not in ("content", "filePath")})
    data["songs"] = clean_songs
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    # pretty pro schránku už dělá playlist_to_text; QR chce compact pro úsporu
    if len(payload) > MAX_QR_LENGTH:
        return None, f"Setlist je příliš velký pro QR ({len(payload)} znaků, limit {MAX_QR_LENGTH}). Použijte soubor nebo HTML."
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
