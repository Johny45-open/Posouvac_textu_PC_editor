"""
Přístupný dialog pro editaci zarážek na konkrétní písni.
NVDA: každý prvek má AccessibleName/Description, QLabel.buddy, tab order.
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QSpinBox, QDialogButtonBox, QMessageBox, QGroupBox
)
from PyQt6.QtCore import Qt
import song_parser


class StopMarksDialog(QDialog):
    def __init__(self, entry: dict, parent=None):
        super().__init__(parent)
        self.entry = entry  # dict s content, stopMarks
        self.setWindowTitle(f"Zarážky – {entry.get('artist')} – {entry.get('title')}")
        self.setMinimumSize(700, 500)
        self._ordered_cache = []
        self._init_ui()
        self._refresh()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # Info
        info = QLabel(
            "Vyberte řádek písně a přidejte pauzu. Pauza se vloží jako samostatný řádek "
            "{stop:N} před vybraný řádek a na telefonu zastaví posuv na N taktů."
        )
        info.setWordWrap(True)
        info.setAccessibleName("Nápověda k zarážkám")
        layout.addWidget(info)

        # Hlavní splitter: vlevo řádky, vpravo zarážky
        main_row = QHBoxLayout()

        # --- Řádky písně ---
        left_box = QGroupBox("Řádky písně")
        left_layout = QVBoxLayout(left_box)
        self.lines_label = QLabel("Seznam řádků:")
        self.lines_list = QListWidget()
        self.lines_list.setAccessibleName("Seznam řádků písně")
        self.lines_list.setAccessibleDescription(
            "Šipkami vyberte řádek, před který se vloží pauza. Číslování odpovídá pořadí v souboru."
        )
        self.lines_list.setAlternatingRowColors(True)
        self.lines_label.setBuddy(self.lines_list)
        left_layout.addWidget(self.lines_label)
        left_layout.addWidget(self.lines_list)
        main_row.addWidget(left_box, 3)

        # --- Zarážky ---
        right_box = QGroupBox("Zarážky v písni")
        right_layout = QVBoxLayout(right_box)
        self.marks_label = QLabel("Seznam zarážek:")
        self.marks_list = QListWidget()
        self.marks_list.setAccessibleName("Seznam zarážek")
        self.marks_list.setAccessibleDescription(
            "Každá položka je pauza v počtu taktů před konkrétním řádkem. Enter nebo tlačítko Odebrat ji smaže."
        )
        self.marks_label.setBuddy(self.marks_list)
        right_layout.addWidget(self.marks_label)
        right_layout.addWidget(self.marks_list)
        main_row.addWidget(right_box, 2)

        layout.addLayout(main_row)

        # --- Ovládání přidání ---
        add_row = QHBoxLayout()
        self.bars_label = QLabel("Takty:")
        self.bars_spin = QSpinBox()
        self.bars_spin.setAccessibleName("Délka pauzy v taktech")
        self.bars_spin.setAccessibleDescription("1 až 16 taktů, výchozí 2. Na pomalou 4, na rychlou 2.")
        self.bars_spin.setMinimum(1)
        self.bars_spin.setMaximum(16)
        self.bars_spin.setValue(2)
        self.bars_spin.setToolTip("Počet taktů pauzy (1–16)")
        self.bars_label.setBuddy(self.bars_spin)
        add_row.addWidget(self.bars_label)
        add_row.addWidget(self.bars_spin)

        self.add_btn = QPushButton("Přidat zarážku před vybraný řádek (&P)")
        self.add_btn.setAccessibleName("Přidat zarážku před vybraný řádek")
        self.add_btn.setAccessibleDescription(
            "Vloží {stop:N} před označený řádek. N je počet taktů ze spinboxu."
        )
        self.add_btn.clicked.connect(self._add_mark)
        add_row.addWidget(self.add_btn)

        self.remove_btn = QPushButton("Odebrat vybranou zarážku (&O)")
        self.remove_btn.setAccessibleName("Odebrat vybranou zarážku")
        self.remove_btn.clicked.connect(self._remove_mark)
        add_row.addWidget(self.remove_btn)

        add_row.addStretch()
        layout.addLayout(add_row)

        # --- Tlačítka dialogu ---
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        # Přístupné popisky
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setText("Uložit")
        self.button_box.button(QDialogButtonBox.StandardButton.Cancel).setText("Zrušit")
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setAccessibleName("Uložit zarážky")
        self.button_box.button(QDialogButtonBox.StandardButton.Cancel).setAccessibleName("Zrušit změny zarážek")
        layout.addWidget(self.button_box)

        # Tab order
        self.setTabOrder(self.lines_list, self.marks_list)
        self.setTabOrder(self.marks_list, self.bars_spin)
        self.setTabOrder(self.bars_spin, self.add_btn)
        self.setTabOrder(self.add_btn, self.remove_btn)

        # Klávesové zkratky navíc
        self.lines_list.itemDoubleClicked.connect(lambda _: self._add_mark())

    def _refresh(self):
        content = self.entry.get("content") or ""
        marks: list[dict] = list(self.entry.get("stopMarks") or [])
        ordered = song_parser.ordered_lines(content)
        self._ordered_cache = ordered

        # Naplnit řádky (číslované, s označením kde už je pauza)
        self.lines_list.clear()
        mark_indices = {m.get("lineIndex") for m in marks if m.get("lineIndex") is not None}
        # také podle lineText
        mark_texts = {m.get("lineText", "").strip() for m in marks}
        for idx, ln in enumerate(ordered):
            is_stop = any(e.type == song_parser.ElementType.stopMark for e in ln)
            txt = song_parser.line_text(ln)
            if is_stop:
                label = f"{idx+1}. [Pauza {next((e.stop_mark_bars for e in ln if e.type == song_parser.ElementType.stopMark), 2)} taktů]"
            else:
                label = f"{idx+1}. {txt[:80]}"
                if idx in mark_indices or txt in mark_texts:
                    label += "  ← zarážka před tímto řádkem"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, idx)
            if is_stop:
                # odlišit vizuálně, ale pro NVDA hlavně text
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.lines_list.addItem(item)

        # Naplnit zarážky
        self.marks_list.clear()
        for i, m in enumerate(marks):
            bars = m.get("bars", 2)
            lt = m.get("lineText") or ""
            li = m.get("lineIndex")
            if lt:
                label = f"{i+1}. Pauza {bars} taktů před: „{lt[:60]}“"
            elif li is not None:
                label = f"{i+1}. Pauza {bars} taktů před řádkem {int(li)+1}"
            else:
                label = f"{i+1}. Pauza {bars} taktů"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, i)
            self.marks_list.addItem(item)

        self.lines_list.setCurrentRow(0)

    def _add_mark(self):
        row = self.lines_list.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Varování", "Vyberte řádek, před který se má vložit zarážka.")
            return
        idx = self.lines_list.currentItem().data(Qt.ItemDataRole.UserRole)
        # nedovolit přidat před samotnou direktivu
        ordered = self._ordered_cache
        if 0 <= idx < len(ordered) and any(e.type == song_parser.ElementType.stopMark for e in ordered[idx]):
            QMessageBox.warning(self, "Varování", "Před pauzu nelze vložit další pauzu. Vyberte textový řádek.")
            return
        bars = int(self.bars_spin.value())
        line_text = song_parser.line_text(ordered[idx]) if 0 <= idx < len(ordered) else ""
        # zkontrolovat duplicitu
        for m in (self.entry.get("stopMarks") or []):
            if m.get("lineIndex") == idx or (line_text and m.get("lineText") == line_text):
                QMessageBox.warning(self, "Varování", "Před tímto řádkem už zarážka existuje. Nejprve ji odeberte.")
                return
        new_mark = {"lineText": line_text, "lineIndex": int(idx), "bars": int(bars)}
        self.entry.setdefault("stopMarks", []).append(new_mark)
        self._refresh()
        # fokus na novou zarážku
        self.marks_list.setCurrentRow(self.marks_list.count() - 1)
        if self.parent():
            try:
                self.parent().statusBar().showMessage(f"Přidána zarážka {bars} taktů před řádek {idx+1}.")
            except Exception:
                pass

    def _remove_mark(self):
        row = self.marks_list.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Varování", "Vyberte zarážku k odebrání.")
            return
        marks = self.entry.get("stopMarks") or []
        if 0 <= row < len(marks):
            removed = marks.pop(row)
            self._refresh()
            if self.parent():
                try:
                    self.parent().statusBar().showMessage(f"Odebrána zarážka {removed.get('bars')} taktů.")
                except Exception:
                    pass

    def get_result(self) -> list[dict]:
        return list(self.entry.get("stopMarks") or [])
