"""
Port database.dart diakritiky pro PC editor.
Zrcadlí _stripDiacritics, _normForMatch, _isDiacriticOnly,
_resolveComposite, lookupDiacritic, learnDiacritic validace.
CSV formát: bezDiakritiky,sDiakritikou (BOM, , i ;, uvozovky).
"""
import csv
import io
import re

_STRIP_MAP = {
    'á': 'a', 'č': 'c', 'ď': 'd', 'é': 'e', 'ě': 'e', 'í': 'i', 'ň': 'n',
    'ó': 'o', 'ř': 'r', 'š': 's', 'ť': 't', 'ú': 'u', 'ů': 'u', 'ý': 'y', 'ž': 'z',
    'Á': 'A', 'Č': 'C', 'Ď': 'D', 'É': 'E', 'Ě': 'E', 'Í': 'I', 'Ň': 'N',
    'Ó': 'O', 'Ř': 'R', 'Š': 'S', 'Ť': 'T', 'Ú': 'U', 'Ů': 'U', 'Ý': 'Y', 'Ž': 'Z',
    'ä': 'a', 'ë': 'e', 'ï': 'i', 'ö': 'o', 'ü': 'u',
    'Ä': 'A', 'Ë': 'E', 'Ï': 'I', 'Ö': 'O', 'Ü': 'U',
    'à': 'a', 'è': 'e', 'ì': 'i', 'ò': 'o', 'ù': 'u',
    'À': 'A', 'È': 'E', 'Ì': 'I', 'Ò': 'O', 'Ù': 'U',
    'â': 'a', 'ê': 'e', 'î': 'i', 'ô': 'o', 'û': 'u',
    'Â': 'A', 'Ê': 'E', 'Î': 'I', 'Ô': 'O', 'Û': 'U',
}

_ARTIST_DELIMITER = re.compile(
    r'(\s*,\s*|\s+a\s+|\s+&\s+|\s*;\s*|\s*/\s*|\s+feat[.,]?\s*[, ]*|\s+ft[.,]?\s*[, ]*|\s+featuring\s+)',
    re.IGNORECASE,
)
_FEAT_PAREN = re.compile(
    r'^(.*)\s*\(\s*(feat|ft|featuring)[.,]?\s*[, ]*(.+?)\s*\)\s*$',
    re.IGNORECASE,
)
_FEAT_BARE = re.compile(
    r'^(.*)\s+(feat|ft|featuring)[.,]?\s*[, ]*(.+)$',
    re.IGNORECASE,
)


def strip_diacritics(text: str) -> str:
    out = text or ""
    for k, v in _STRIP_MAP.items():
        out = out.replace(k, v)
    return out


def _norm(text: str) -> str:
    return re.sub(r'\s+', ' ', strip_diacritics((text or "").strip().lower())).strip()


def norm_for_match(text: str) -> str:
    return _norm(text)


def is_diacritic_only(raw: str, corrected: str) -> bool:
    return _norm(raw) == _norm(corrected)


def _lookup_single(part: str, dmap: dict) -> str | None:
    trimmed = (part or "").strip()
    if not trimmed:
        return None
    key = _norm(trimmed)
    corrected = dmap.get(key)
    if corrected is not None and corrected != trimmed:
        if _norm(corrected) != key:
            return None
        return corrected
    return None


def _resolve_composite_inner(raw: str, dmap: dict) -> str | None:
    if not (raw or "").strip():
        return None
    if not _ARTIST_DELIMITER.search(raw):
        return None
    def on_match(m):
        return m.group(0)
    parts = _ARTIST_DELIMITER.split(raw)
    # splitMapJoin emulace
    resolved = _ARTIST_DELIMITER.sub(lambda m: "\x00" + m.group(0) + "\x00", raw)
    tokens = resolved.split("\x00")
    out_tokens = []
    for tok in tokens:
        if not tok:
            continue
        if _ARTIST_DELIMITER.fullmatch(tok):
            out_tokens.append(tok)
        else:
            if not tok.strip():
                out_tokens.append(tok)
                continue
            corrected = dmap.get(_norm(tok))
            if corrected is not None and corrected != tok:
                if _norm(corrected) != _norm(tok):
                    out_tokens.append(tok)
                else:
                    out_tokens.append(corrected)
            else:
                out_tokens.append(tok)
    resolved_str = "".join(out_tokens)
    return resolved_str if resolved_str != raw else None


def resolve_composite(raw: str, dmap: dict) -> str | None:
    if not (raw or "").strip():
        return None
    direct = dmap.get(_norm(raw))
    if direct is not None and direct != raw:
        if _norm(direct) == _norm(raw):
            return direct
    # 1) závorková feat verze
    m = _FEAT_PAREN.match(raw)
    if m:
        main_part = m.group(1).strip()
        feat_tag = m.group(2).strip()
        feat_part = m.group(3).strip()
        if main_part and feat_part:
            fixed_main = _lookup_single(main_part, dmap) or _resolve_composite_inner(main_part, dmap)
            fixed_feat = _lookup_single(feat_part, dmap) or _resolve_composite_inner(feat_part, dmap)
            new_main = fixed_main if fixed_main is not None else main_part
            new_feat = fixed_feat if fixed_feat is not None else feat_part
            if new_main != main_part or new_feat != feat_part:
                low = feat_tag.lower()
                if low.startswith('featuring'):
                    nt = 'featuring'
                elif 'ft' in low and 'fea' not in low:
                    nt = 'ft.'
                else:
                    nt = 'feat.'
                return f"{new_main} ({nt} {new_feat})"
    # 2) bare feat
    m2 = _FEAT_BARE.match(raw)
    if m2:
        main_part = m2.group(1).strip()
        feat_tag = m2.group(2).strip()
        feat_part = m2.group(3).strip()
        if main_part and feat_part:
            fixed_main = _lookup_single(main_part, dmap) or _resolve_composite_inner(main_part, dmap)
            fixed_feat = _lookup_single(feat_part, dmap) or _resolve_composite_inner(feat_part, dmap)
            new_main = fixed_main if fixed_main is not None else main_part
            new_feat = fixed_feat if fixed_feat is not None else feat_part
            if new_main != main_part or new_feat != feat_part:
                low = feat_tag.lower()
                if low.startswith('featuring'):
                    nt = 'featuring'
                elif 'ft' in low and 'fea' not in low:
                    nt = 'ft.'
                else:
                    nt = 'feat.'
                return f"{new_main} {nt} {new_feat}"
    if not _ARTIST_DELIMITER.search(raw):
        return direct if direct is not None and direct != raw and _norm(direct) == _norm(raw) else None
    # kompozitní s oddělovači + rekurze pro feat uvnitř částí
    # splitMapJoin
    # oddělovače zachovat
    pattern = _ARTIST_DELIMITER
    resolved = pattern.sub(lambda x: "\x00" + x.group(0) + "\x00", raw)
    toks = resolved.split("\x00")
    out = []
    for tok in toks:
        if not tok:
            continue
        if pattern.fullmatch(tok):
            out.append(tok)
        else:
            if not tok.strip():
                out.append(tok)
                continue
            # zkus rekurzi pro feat uvnitř části
            sub = resolve_composite(tok.strip(), dmap) if tok.strip() != raw else None
            if sub is not None:
                out.append(sub)
                continue
            corr = dmap.get(_norm(tok))
            if corr is not None and corr != tok:
                if _norm(corr) != _norm(tok):
                    out.append(tok)
                else:
                    out.append(corr)
            else:
                out.append(tok)
    res = "".join(out)
    return res if res != raw else None


def lookup_diacritic(raw_text: str, dmap: dict) -> str | None:
    key = _norm(raw_text)
    if not key:
        return None
    row = dmap.get(key)
    if row is not None:
        if _norm(row) != key:
            # otrávený záznam
            pass
        else:
            return row
    is_composite = bool(_ARTIST_DELIMITER.search(raw_text) or _FEAT_PAREN.search(raw_text) or _FEAT_BARE.search(raw_text))
    if not is_composite:
        return None
    if not dmap:
        return None
    return resolve_composite(raw_text, dmap)


def _parse_csv_line_smart(line: str) -> list[str]:
    # zkus čárku, pak středník – respektuje uvozovky
    for delim in [',', ';']:
        try:
            reader = csv.reader(io.StringIO(line), delimiter=delim, quotechar='"', doublequote=True, skipinitialspace=True)
            parts = next(reader)
            if len(parts) >= 2:
                if delim == ',' and len(parts) == 1 and ';' in line:
                    continue
                return [p.strip() for p in parts]
            if len(parts) == 1 and delim == ',' and ';' in line:
                continue
            if len(parts) >= 1:
                # pokud 1 sloupec a zkoušíme čárku, nech padnout na středník
                if delim == ',' and ';' in line:
                    continue
                return [p.strip() for p in parts]
        except Exception:
            continue
    return [p.strip() for p in line.split(',')]


def load_diacritic_csv(path: str) -> tuple[bool, dict | str, dict]:
    """
    Načte slovnik CSV. Vrací (True, map, info) nebo (False, err, info).
    map: {normKey: corrected}
    info: {imported, skipped, errors}
    Libovolný název souboru, header bezDiakritiky,sDiakritikou (case-insensitive) nebo bez headeru.
    """
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            content = f.read()
    except Exception as e:
        return False, str(e), {}
    lines = content.splitlines()
    if not lines:
        return False, "Prázdný soubor.", {}
    # detekce headeru
    header_parts = _parse_csv_line_smart(lines[0])
    lower = [h.lower().strip() for h in header_parts]
    has_header = ('bezdiakritiky' in lower or 'bez diakritiky' in lower or 'norm_key' in lower or 'normkey' in lower) and ('sdiakritikou' in lower or 's diakritikou' in lower or 'corrected' in lower)
    start = 1 if has_header else 0
    # pokud  header obsahuje bezDiakritiky,sDiakritikou ale s mezerami/pomlčkami, normalizuj
    # jednodušší: pokud první řádek obsahuje písmena bez čísel a druhý řádek vypadá jako data, bereme header
    if not has_header:
        # heuristika: první řádek obsahuje 'bez' a 'diakrit' současně
        first_low = lines[0].lower()
        if 'bez' in first_low and 'diakrit' in first_low:
            has_header = True
            start = 1
    dmap: dict[str, str] = {}
    imported = 0
    skipped = 0
    expanded = 0
    errors: list[str] = []
    for idx in range(start, len(lines)):
        line = lines[idx].strip()
        if not line:
            continue
        parts = _parse_csv_line_smart(line)
        if len(parts) < 2:
            skipped += 1
            errors.append(f"ř.{idx+1}: {line}")
            continue
        # parts[0] = bez, parts[1] = s
        raw_key = parts[0].split(';')[0].strip().strip('"').strip()
        raw_val = parts[1].strip()
        if ';' in raw_val:
            raw_val = raw_val.split(';')[0].strip()
        raw_val = re.sub(r'[;\)]+$', '', raw_val).strip().strip('"').strip()
        # očistit uvozovky kolem hodnoty (csv už je ořezal, ale pro jistotu)
        raw_val = raw_val.strip('"').strip()
        raw_key = raw_key.strip('"').strip()
        key = _norm(raw_key)
        val = raw_val.strip()
        if not key or not val or key == val.lower().strip():
            skipped += 1
            continue
        if _norm(val) != key:
            skipped += 1
            errors.append(f"ř.{idx+1}: odmítnuto (překlep) {key} -> {val}")
            continue
        if key not in dmap or dmap[key] != val:
            dmap[key] = val
            imported += 1
        else:
            # duplicitní stejný záznam – nepočítat jako nový?
            pass
        # --- expanze kombinovaných klíčů Artist - Title ---
        # zrcadlí library_model._parse_filename_artist_title: poslední výskyt \s+[-–—]\s+
        try:
            # najít poslední oddělovač v raw_key i raw_val (musí být oba)
            key_matches = list(re.finditer(r'\s+[–—-]\s+', raw_key))
            val_matches = list(re.finditer(r'\s+[–—-]\s+', raw_val))
            if key_matches and val_matches:
                km = key_matches[-1]
                vm = val_matches[-1]
                a_raw = raw_key[:km.start()].strip()
                b_raw = raw_key[km.end():].strip()
                a_corr = raw_val[:vm.start()].strip()
                b_corr = raw_val[vm.end():].strip()
                for part_raw, part_corr in ((a_raw, a_corr), (b_raw, b_corr)):
                    if not part_raw or not part_corr:
                        continue
                    nk = _norm(part_raw)
                    nv = part_corr.strip()
                    if not nk or not nv or nk == nv.lower().strip():
                        continue
                    if _norm(nv) != nk:
                        continue
                    if nk not in dmap:
                        dmap[nk] = nv
                        expanded += 1
                    elif dmap[nk] != nv:
                        # kolize: nechat původní, zalogovat
                        errors.append(f"ř.{idx+1}: expanze kolize {nk} -> {nv} (ponecháno {dmap[nk]})")
        except Exception:
            pass
    return True, dmap, {"imported": imported, "skipped": skipped, "expanded": expanded, "errors": errors, "path": path}


def find_diacritic_repairs(entries: list[dict], dmap: dict) -> tuple[list[dict], list[dict]]:
    """
    Pro PC editor: najde kandidáty na opravu.
    entries: list[{artist,title,filePath,...}]
    Vrací (candidates, unrepaired)
    candidates: [{index, currentArtist, currentTitle, newArtist, newTitle, filePath}]
    unrepaired: [{index, artist, title, filePath, reason, normTitle, normArtist}]
    Port database.dart:1170 findDiacriticRepairs + getDiacriticUnrepairedWithReason
    """
    if not dmap:
        # vše bez návrhu
        unrepaired = []
        for i, e in enumerate(entries):
            unrepaired.append({
                "index": i,
                "artist": e.get("artist") or "",
                "title": e.get("title") or "",
                "filePath": e.get("filePath") or "",
                "reason": "missingInMap",
                "normTitle": _norm(e.get("title") or ""),
                "normArtist": _norm(e.get("artist") or ""),
            })
        return [], unrepaired
    # filtr otrávených
    clean_map = {k: v for k, v in dmap.items() if _norm(v) == k}
    candidates = []
    candidate_idxs = set()
    for i, e in enumerate(entries):
        artist = e.get("artist") or ""
        title = e.get("title") or ""
        direct_title = clean_map.get(_norm(title))
        composite_artist = resolve_composite(artist, clean_map)
        direct_artist = clean_map.get(_norm(artist))
        resolved_title = direct_title if direct_title is not None and _norm(direct_title) == _norm(title) else None
        resolved_artist = None
        if composite_artist is not None:
            # feat normalizace (feat, -> feat.) mění interpunkci, ale je povolená
            if _norm(composite_artist) == _norm(artist) or re.sub(r'[.,]', '', _norm(composite_artist)) == re.sub(r'[.,]', '', _norm(artist)):
                resolved_artist = composite_artist
            else:
                # i tak povolit pokud rozdíl je jen v diakritice + feat interpunkci – resolve_composite už validoval části
                # fallback: akceptovat pokud strip_diacritics bez ., je shodný
                if strip_diacritics(composite_artist).lower().replace('.', '').replace(',', '').strip() == strip_diacritics(artist).lower().replace('.', '').replace(',', '').strip():
                    resolved_artist = composite_artist
        if resolved_artist is None and direct_artist is not None and _norm(direct_artist) == _norm(artist):
            resolved_artist = direct_artist
        changed_title = resolved_title is not None and resolved_title != title
        changed_artist = resolved_artist is not None and resolved_artist != artist
        if not changed_title and not changed_artist:
            continue
        candidate_idxs.add(i)
        candidates.append({
            "index": i,
            "currentArtist": artist,
            "currentTitle": title,
            "newArtist": resolved_title if False else (resolved_artist if changed_artist else artist) if changed_artist else artist,
            "newTitle": resolved_title if changed_title else title,
            "filePath": e.get("filePath") or "",
        })
        # opravit newArtist/newTitle správně
        c = candidates[-1]
        c["newArtist"] = resolved_artist if changed_artist else artist
        c["newTitle"] = resolved_title if changed_title else title

    # unrepaired
    unrepaired = []
    for i, e in enumerate(entries):
        if i in candidate_idxs:
            continue
        artist = e.get("artist") or ""
        title = e.get("title") or ""
        norm_title = _norm(title)
        norm_artist = _norm(artist)
        has_title_dia = strip_diacritics(title) != title
        has_artist_dia = strip_diacritics(artist) != artist
        title_in_map = norm_title in clean_map
        artist_in_map = (norm_artist in clean_map) or (resolve_composite(artist, clean_map) is not None)
        if (has_title_dia or has_artist_dia) and not title_in_map and not artist_in_map:
            reason = "alreadyCorrect"
        elif not title_in_map and not artist_in_map:
            is_comp = bool(_ARTIST_DELIMITER.search(artist) or _FEAT_PAREN.search(artist) or _FEAT_BARE.search(artist))
            reason = "compositeNoMatch" if is_comp else "missingInMap"
        else:
            reason = "alreadyCorrect"
        unrepaired.append({
            "index": i,
            "artist": artist,
            "title": title,
            "filePath": e.get("filePath") or "",
            "reason": reason,
            "normTitle": norm_title,
            "normArtist": norm_artist,
        })
    return candidates, unrepaired
