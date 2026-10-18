"""
Port lib/chord_pro_parser.dart pro PC editor.
Záměrně 1:1 logika, aby zarážky seděly s telefonem.
"""
import re
from enum import Enum
from dataclasses import dataclass
from typing import Optional


class ElementType(Enum):
    text = "text"
    chord = "chord"
    comment = "comment"
    stopMark = "stopMark"


@dataclass
class ChordProElement:
    type: ElementType
    content: str
    stop_mark_bars: Optional[int] = None


@dataclass
class ChordProSection:
    lines: list  # list[list[ChordProElement]]
    title: Optional[str] = None


def parse(content: str) -> list[ChordProSection]:
    """Port ChordProParser.parse – lib/chord_pro_parser.dart:19."""
    lines = content.split("\n")
    sections: list[ChordProSection] = []
    current_lines: list[list[ChordProElement]] = []
    current_section_title: Optional[str] = None

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("{") and line.endswith("}"):
            directive = line[1:-1].strip()
            # soc / chorus
            if directive.startswith("soc") or directive.startswith("chorus"):
                current_section_title = "Refrén"
            elif directive.startswith("eoc"):
                sections.append(ChordProSection(list(current_lines), title=current_section_title))
                current_lines = []
                current_section_title = None
            elif directive.startswith("c:"):
                current_lines.append([ChordProElement(ElementType.comment, directive[2:].strip())])
            elif directive.startswith("stop:") or directive.startswith("pause:"):
                parts = directive.split(":", 1)
                bars = 0
                if len(parts) > 1:
                    try:
                        bars = int(parts[1].strip())
                    except Exception:
                        bars = 0
                current_lines.append([ChordProElement(ElementType.stopMark, "Pauza", stop_mark_bars=bars)])
            # ostatní direktivy ignorujeme jako v Dartu
            continue
        current_lines.append(_parse_line(line))

    if current_lines:
        sections.append(ChordProSection(list(current_lines), title=current_section_title))
    return sections


def _parse_line(line: str) -> list[ChordProElement]:
    elems: list[ChordProElement] = []
    # stejné jako Dart: \[([^\]]*)\]|([^[\]]+)
    for m in re.finditer(r"\[([^\]]*)\]|([^[\]]+)", line):
        if m.group(1) is not None:
            elems.append(ChordProElement(ElementType.chord, m.group(1)))
        elif m.group(2) is not None:
            elems.append(ChordProElement(ElementType.text, m.group(2)))
    return elems


def ordered_lines(content: str) -> list[list[ChordProElement]]:
    """Port orderedLines – lib/chord_pro_parser.dart:75."""
    return [ln for sec in parse(content) for ln in sec.lines]


def line_text(line: list[ChordProElement]) -> str:
    """Port lineText – lib/chord_pro_parser.dart:79."""
    return "".join(e.content for e in line).strip()


def stop_marks_in_lines(content: str) -> list[dict]:
    """Port stopMarksInLines – lib/chord_pro_parser.dart:84. Vrací [{index,bars}]."""
    marks: list[dict] = []
    lines = ordered_lines(content)
    for i, line in enumerate(lines):
        for e in line:
            if e.type == ElementType.stopMark:
                marks.append({"index": i, "bars": e.stop_mark_bars or 0})
    return marks


def file_lines_raw(content: str) -> list[str]:
    """Původní řádky souboru včetně prázdných – pro editaci direktiv."""
    return content.split("\n")


def directive_for_bars(bars: int, use_pause: bool = False) -> str:
    tag = "pause" if use_pause else "stop"
    return f"{{{tag}:{int(bars)}}}"


# --- Fyzická mapa řádků – jednotný indexový prostor pro zarážky ---
#
# lineIndex zarážky = index CÍLOVÉHO řádku v prostoru textu BEZ stop direktiv
# {stop:N}/{pause:N}. Takto se zarážky načítají, zobrazují i vkládají.
# Direktivy se do ordered_lines() započítávají jako řádky, proto je jejich
# přítomnost v textu nesmí posouvat cílové indexy žádné další operace.

# Druhy fyzických řádků (konzistentní s parse()):
#   'empty'   – prázdný řádek (nevstupuje do ordered_lines)
#   'text'    – textový řádek (vstupuje do ordered_lines, je to čistý řádek)
#   'comment' – direktiva {c:...} (vstupuje do ordered_lines, je to čistý řádek)
#   'stop'    – direktiva {stop:N}/{pause:N} (vstupuje do ordered_lines, NENÍ čistý řádek)
#   'section' – {soc}/{eoc} (nevstupuje do ordered_lines)
#   'other'   – jiná direktiva (nevstupuje do ordered_lines)

def split_physical_lines(content: str) -> list[tuple[int, str, str]]:
    """
    Rozdělí content na fyzické řádky a určí jejich druh stejnou logikou jako parse().
    Vrací seznam (fyzický_index, druh, zbytek_řádku).
    """
    out: list[tuple[int, str, str]] = []
    for i, raw in enumerate(file_lines_raw(content or "")):
        stripped = raw.strip()
        if not stripped:
            out.append((i, "empty", stripped))
            continue
        if stripped.startswith("{") and stripped.endswith("}"):
            directive = stripped[1:-1].strip()
            if directive.startswith("soc") or directive.startswith("chorus") or directive.startswith("eoc"):
                out.append((i, "section", directive))
            elif directive.startswith("c:"):
                out.append((i, "comment", directive))
            elif directive.startswith("stop:") or directive.startswith("pause:"):
                out.append((i, "stop", directive))
            else:
                out.append((i, "other", directive))
            continue
        out.append((i, "text", stripped))
    return out


def clean_line_text(kind: str, payload: str) -> str:
    """Text čistého řádku ('text'/'comment') – shodný s line_text() nad ordered řádkem."""
    if kind == "comment":
        return payload[2:].strip()
    return line_text(_parse_line(payload))


def clean_line_indices(content: str) -> list[int]:
    """Fyzické indexy čistých řádků (bez stop direktiv) v pořadí čistého indexového prostoru."""
    return [p for (p, kind, _pay) in split_physical_lines(content) if kind in ("text", "comment")]


def parse_directive_bars(directive: str) -> int:
    """Počet taktů z 'stop:4'/'pause:4' (0 pokud chybí nebo není číslo)."""
    parts = (directive or "").split(":", 1)
    if len(parts) > 1:
        try:
            return int(parts[1].strip())
        except Exception:
            return 0
    return 0


def insert_stop_directive(
    content: str,
    target_line_index: int,
    bars: int,
    use_pause: bool = False,
    expected_line_text: Optional[str] = None,
) -> str:
    """
    Vloží direktivu {stop:N} před cílový řádek.

    target_line_index je index CÍLOVÉHO řádku v prostoru BEZ stop direktiv
    (tj. počítají se jen textové řádky a direktivy {c:...}); direktivy
    {stop:N}/{pause:N} přítomné v textu index nijak neposouvají. Hodnota
    index == počet čistých řádků znamená „za posledním řádkem textu“.

    Pokud je expected_line_text neprázdný, ověří se, že cílový řádek má
    tento text; při neshodě nebo neplatném indexu funkce vyhodí ValueError
    a původní obsah zůstane beze změny (nikdy netichom nepřesouvá direktivu
    na konec souboru).
    """
    try:
        idx = int(target_line_index)
    except (TypeError, ValueError):
        raise ValueError(f"Neplatný lineIndex: {target_line_index!r} – očekáváváno celé číslo.")
    try:
        bars_int = int(bars)
    except (TypeError, ValueError):
        raise ValueError(f"Neplatný počet taktů: {bars!r}")
    bars_int = max(1, min(16, bars_int))
    directive = directive_for_bars(bars_int, use_pause)

    clean = [(p, kind, payload) for (p, kind, payload) in split_physical_lines(content)
             if kind in ("text", "comment")]
    if idx < 0 or idx > len(clean):
        raise ValueError(
            f"lineIndex {idx} je mimo rozsah 0..{len(clean)} "
            f"(počet řádků textu bez direktiv)."
        )

    if idx == len(clean):
        # Za posledním čistým řádkem textu. Pokud ale zarážka udává neprázdný
        # lineText, tvrdí, že existuje cílový řádek – ten za koncem textu není
        # (typický příznak starých, „špinavých“ indexů). Raději chyba než
        # tiché vložení na konec souboru.
        if expected_line_text is not None and str(expected_line_text).strip():
            raise ValueError(
                f"lineIndex {idx} je za koncem textu, ale lineText "
                f"{str(expected_line_text).strip()!r} udává cílový řádek – údaje si odporují."
            )
        insert_at = clean[-1][0] + 1 if clean else 0
    else:
        _p, kind, payload = clean[idx]
        target_text = clean_line_text(kind, payload)
        if expected_line_text is not None and str(expected_line_text).strip():
            expected = str(expected_line_text).strip()
            if expected != target_text:
                raise ValueError(
                    f"lineText nesouhlasí s řádkem {idx + 1}: "
                    f"očekáváno {expected!r}, nalezeno {target_text!r}."
                )
        insert_at = clean[idx][0]

    raw_lines = file_lines_raw(content)
    raw_lines.insert(insert_at, directive)
    return "\n".join(raw_lines)


def remove_stop_directive_at(content: str, ordered_index: int) -> tuple[str, bool]:
    """
    Odstraní první stop direktivu, jejíž cílový řádek leží na daném indexu
    v prostoru BEZ stop direktiv (stejný význam jako u insert_stop_directive).
    Vrací (nový obsah, odstraněno?).
    """
    clean_count = 0
    for p, kind, _payload in split_physical_lines(content):
        if kind == "stop":
            if clean_count == ordered_index:
                raw_lines = file_lines_raw(content)
                del raw_lines[p]
                return "\n".join(raw_lines), True
        elif kind in ("text", "comment"):
            clean_count += 1
    return content, False


def count_stop_directives(content: str) -> int:
    return len(stop_marks_in_lines(content))
