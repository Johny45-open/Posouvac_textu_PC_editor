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


def insert_stop_directive(content: str, target_line_index: int, bars: int, use_pause: bool = False) -> str:
    """
    Vloží direktivu {stop:N} před cílový logický řádek (podle ordered_lines).
    Mapuje logický index na fyzický řádek v souboru (ignoruje prázdné/direktivy).
    Pokud se nepodaří namapovat, vloží na konec.
    """
    bars = max(1, min(16, int(bars)))
    directive = directive_for_bars(bars, use_pause)
    # Najít fyzický řádek odpovídající ordered_lines[target]
    ordered = ordered_lines(content)
    if not ordered or target_line_index < 0 or target_line_index >= len(ordered):
        # fallback: na konec
        suffix = "" if content.endswith("\n") else "\n"
        return content + suffix + directive + "\n"
    target_text = line_text(ordered[target_line_index])
    # Projít raw řádky a najít ten, jehož parse odpovídá target_text
    raw_lines = file_lines_raw(content)
    # Sestavíme mapu: fyzický index -> ordered index (jen neprázdné nedirektivní)
    ordered_ptr = 0
    for phys_idx, raw in enumerate(raw_lines):
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("{") and stripped.endswith("}"):
            # direktiva – odpovídá ordered linii typu stopMark/comment/soc, ale my hledáme textovou linii
            # Zjistíme, zda ordered[ordered_ptr] je direktivní linie
            if ordered_ptr < len(ordered):
                # pokud je to direktivní linie, posun ordered_ptr a pokračuj
                has_directive = any(e.type in (ElementType.stopMark, ElementType.comment) for e in ordered[ordered_ptr])
                if has_directive:
                    if ordered_ptr == target_line_index:
                        # cíl je samotná direktiva – vložit před ni
                        raw_lines.insert(phys_idx, directive)
                        return "\n".join(raw_lines)
                    ordered_ptr += 1
                    continue
            continue
        # textová linie
        if ordered_ptr < len(ordered) and line_text(ordered[ordered_ptr]) == stripped or line_text(ordered[ordered_ptr]) == line_text(_parse_line(stripped)):
            if ordered_ptr == target_line_index:
                raw_lines.insert(phys_idx, directive)
                return "\n".join(raw_lines)
            ordered_ptr += 1
        else:
            # fallback tolerace: porovnáme normalized
            if ordered_ptr < len(ordered) and line_text(ordered[ordered_ptr]) == target_text and ordered_ptr == target_line_index:
                raw_lines.insert(phys_idx, directive)
                return "\n".join(raw_lines)
            if ordered_ptr < len(ordered):
                ordered_ptr += 1
    # nenalezeno -> na konec
    suffix = "" if content.endswith("\n") else "\n"
    return content + suffix + directive + "\n"


def remove_stop_directive_at(content: str, ordered_index: int) -> tuple[str, bool]:
    """
    Odstraní direktivu {stop/pause} na daném ordered indexu. Vrací (nový obsah, odstraněno?).
    """
    ordered = ordered_lines(content)
    if ordered_index < 0 or ordered_index >= len(ordered):
        return content, False
    # ověř, že na indexu je stopMark
    if not any(e.type == ElementType.stopMark for e in ordered[ordered_index]):
        return content, False
    raw_lines = file_lines_raw(content)
    ordered_ptr = 0
    for phys_idx, raw in enumerate(raw_lines):
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("{") and stripped.endswith("}"):
            directive = stripped[1:-1].strip()
            is_stop = directive.startswith("stop:") or directive.startswith("pause:")
            if is_stop and ordered_ptr < len(ordered) and any(e.type == ElementType.stopMark for e in ordered[ordered_ptr]):
                if ordered_ptr == ordered_index:
                    del raw_lines[phys_idx]
                    return "\n".join(raw_lines), True
                ordered_ptr += 1
            elif any(e.type in (ElementType.comment,) for e in ordered[ordered_ptr]) if ordered_ptr < len(ordered) else False:
                ordered_ptr += 1
            continue
        # textová linie – posun
        if ordered_ptr < len(ordered) and not any(e.type == ElementType.stopMark for e in ordered[ordered_ptr]):
            if ordered_ptr == ordered_index:
                # nemělo nastat – target je stop, ale tady je text
                pass
            ordered_ptr += 1
        elif ordered_ptr < len(ordered):
            ordered_ptr += 1
    return content, False


def count_stop_directives(content: str) -> int:
    return len(stop_marks_in_lines(content))
