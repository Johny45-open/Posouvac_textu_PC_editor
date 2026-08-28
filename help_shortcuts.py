"""
Tahák klávesových zkratek – F1 nápověda.
Přístupný, tisknutelný přehled všech zkratek editoru.
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QPushButton, QDialogButtonBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtCore import QUrl


SHORTCUTS_DATA: list[tuple[str, str, str, str]] = [
    # (Akce, Zkratka hlavní, Alias, Kde / mnemonika)
    ("Otevřít složku s písněmi", "Ctrl+O", "Alt+S", "Soubor • S = Složka – F2 knihovna"),
    ("Import z Generátoru", "Ctrl+G", "Alt+G", "Soubor • G = Generátor"),
    ("Načíst knihovnu CSV", "Ctrl+Shift+C", "Alt+C", "Knihovna • C = CSV"),
    ("Výstupní složka", "Ctrl+Shift+V", "Alt+V", "Soubor • V = Výstup"),
    ("Načíst slovník diakritiky", "Ctrl+K", "Alt+K", "Nástroje • K = slovníK"),
    ("Opravit diakritiku – náhled", "Ctrl+D", "Alt+D", "Nástroje • D = Diakritika"),
    ("Hledat / filtr v knihovně", "Ctrl+F", "F6", "Knihovna • F = Filtr – F2 pak Ctrl+F"),
    ("Fokus: Knihovna", "F2", "—", "Zobrazit • F2 = 1. krok"),
    ("Fokus: Detail písně", "F3", "—", "Zobrazit • F3 = 2. krok"),
    ("Fokus: Setlist", "F4", "—", "Zobrazit • F4 = 3. krok"),
    ("Uložit změny písně (detail)", "Ctrl+S", "Ctrl+U / Alt+U", "Detail • U = Uložit – F3"),
    ("Upravit zarážky", "Ctrl+E", "Alt+Z", "Detail • E = Edit / Z = Zarážky – F3"),
    ("Přidat píseň do setlistu", "Enter", "dvojklik", "Knihovna (F2) → Enter"),
    ("Odebrat ze setlistu", "Delete", "—", "Setlist (F4) → Delete"),
    ("Setlist: posun Výše", "Ctrl+↑", "Alt+↑", "Setlist (F4)"),
    ("Setlist: posun Níže", "Ctrl+↓", "Alt+↓", "Setlist (F4)"),
    ("Uložit setlist JSON", "Ctrl+J", "Alt+J", "Export • J = JSON"),
    ("Uložit vše (.txt + JSON)", "Ctrl+Shift+S", "Alt+A", "Export • A = vše"),
    ("Export HTML", "Ctrl+H", "Alt+H", "Export • H = HTML – F5"),
    ("Export Word", "Ctrl+W", "Alt+W", "Export • W = Word"),
    ("Zobrazit QR", "Ctrl+Shift+Q", "Alt+Q", "Export • Q = QR (Ctrl+Q = ukončit)"),
    ("Kopírovat JSON do schránky", "Ctrl+Alt+C", "—", "Export • schránka (Ctrl+Shift+C = CSV)"),
    ("Zkouška hlasu", "Ctrl+T", "—", "Nástroje • T = Test"),
    ("Nápověda – tento tahák", "F1", "Ctrl+/", "Nápověda • F1 = pomoc"),
    # dialog zarážek
    ("Zarážky: Přidat před řádek", "Ctrl+E / Enter", "Alt+P", "Dialog zarážek • E/P"),
    ("Zarážky: Odebrat", "Delete", "Alt+O", "Dialog zarážek • O"),
    ("Zarážky: takty 1-9", "1 … 9", "—", "Dialog zarážek • číslo = takty"),
]


class HelpShortcutsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Klávesové zkratky – tahák (F1)")
        self.setMinimumSize(780, 520)
        layout = QVBoxLayout(self)

        title = QLabel("Klávesové zkratky – zapamatuj si: <b>S-G-K-V načti, F2-F3-F4 uprav, Ctrl+J/A ulož</b>")
        title.setWordWrap(True)
        title.setAccessibleName("Nápověda ke zkratkám – shrnutí")
        title.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(title)

        hint = QLabel(
            "Všechny zkratky fungují odkudkoliv (WindowShortcut). České mnemoniky (Alt+S/G/C…) mají mezinárodní alias "
            "(Ctrl+O/S/G…). V seznamech: Enter = Přidat, Delete = Odebrat, Ctrl+↑/↓ = posun. Podrž Alt – uvidíš podtržená písmena na tlačítkách."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #555; font-size: 11px;")
        hint.setAccessibleName("Vysvětlení principu zkratek")
        layout.addWidget(hint)

        self.table = QTableWidget(len(SHORTCUTS_DATA), 4)
        self.table.setAccessibleName("Tabulka klávesových zkratek")
        self.table.setHorizontalHeaderLabels(["Akce", "Zkratka", "Alias", "Kde / mnemonika"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        for r, (akce, zk, alias, kde) in enumerate(SHORTCUTS_DATA):
            for c, val in enumerate((akce, zk, alias, kde)):
                it = QTableWidgetItem(val)
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                # pro screen reader: accessible
                self.table.setItem(r, c, it)
        layout.addWidget(self.table)

        tip2 = QLabel("Tip: F2 = Knihovna, F3 = Detail, F4 = Setlist, F5 = náhled. Ctrl+F = hledat. Ctrl+E = zarážky (ne Ctrl+Z).")
        tip2.setWordWrap(True)
        tip2.setStyleSheet("color: #333; font-size: 11px;")
        layout.addWidget(tip2)

        btn_row = QHBoxLayout()
        self.print_btn = QPushButton("Vytisknout / Uložit tahák…")
        self.print_btn.setAccessibleName("Vytisknout tahák")
        self.print_btn.setToolTip("Otevře tisk/export – použij Ctrl+P v prohlížeči")
        self.print_btn.clicked.connect(self._print_help)
        btn_row.addWidget(self.print_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(self.reject)
        box.accepted.connect(self.accept)
        box.button(QDialogButtonBox.StandardButton.Close).setText("Zavřít (Esc)")
        layout.addWidget(box)

    def _print_help(self):
        # jednoduchý HTML export do temp a otevřít v prohlížeči
        try:
            import tempfile, os
            html_rows = "".join(
                f"<tr><td>{a}</td><td><b>{z}</b></td><td>{al}</td><td>{k}</td></tr>"
                for a, z, al, k in SHORTCUTS_DATA
            )
            html = f"""<!doctype html><meta charset='utf-8'><title>Tahák – Posouvač PC Editor</title>
<style>body{{font-family:sans-serif;margin:2em}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ccc;padding:6px 8px;text-align:left}}th{{background:#f0f0f0}}</style>
<h1>Posouvač textu – PC Editor – tahák zkratek</h1>
<p><b>S-G-K-V načti, F2-F3-F4 uprav, Ctrl+J/A ulož</b> • F1 kdykoliv nápověda • Podrž Alt pro podtržená písmena</p>
<table><tr><th>Akce</th><th>Zkratka</th><th>Alias</th><th>Kde</th></tr>{html_rows}</table>
<p style='color:#666;font-size:12px'>V seznamech: Enter=Přidat, Delete=Odebrat, Ctrl+↑/↓=posun. Zarážky: Ctrl+E (ne Ctrl+Z).</p>
"""
            fd, path = tempfile.mkstemp(suffix=".html", prefix="posouvac_tahak_")
            os.write(fd, html.encode("utf-8"))
            os.close(fd)
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception:
            pass
