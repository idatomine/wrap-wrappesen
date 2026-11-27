"""Lager wrapped.html: én side der du velger periode, med alle tallene bakt inn.

Siden trenger ingen server. Åpne fila i nettleseren (dobbeltklikk).
Fargene står øverst i wrapped/template.html.
"""
from __future__ import annotations

import json
from pathlib import Path

TEMPLATE = Path(__file__).with_name("template.html")


def write_html(everything: dict, path: str | Path, title: str = "Min Wrapped", rows: int | None = None) -> Path:
    """Skriv siden til `path`. `everything` er det build_all() returnerer."""
    payload = {**everything, "title": title, "rows": rows}
    # "</" kan ikke stå rått inne i en <script>-blokk, ellers tror nettleseren at blokka slutter
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = (TEMPLATE.read_text(encoding="utf-8")
            .replace("__WRAPPED_TITLE__", _escape(title))
            .replace("__WRAPPED_DATA__", data))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
