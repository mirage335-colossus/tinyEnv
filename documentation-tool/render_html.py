"""Render an entirely local, movable HTML code atlas from the snapshot model."""

from __future__ import annotations

import json
from pathlib import Path
import shutil


def render_html(model: dict, output: Path) -> None:
    """Write index.html, its local assets and source snapshot data to output.

    The data is loaded by a normal script tag rather than fetch so the atlas works
    directly from file://, without a web server or access to the source checkout.
    """
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    assets = Path(__file__).resolve().parent
    for name in ("explorer.js", "explorer.css"):
        shutil.copyfile(assets / name, output / name)
    serialized = json.dumps(model, ensure_ascii=False, separators=(",", ":"))
    # Source is data, never HTML; also keep JS-safe escapes for old PDF browsers.
    serialized = serialized.replace("<", "\\u003c").replace(">", "\\u003e")
    serialized = serialized.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    (output / "data.js").write_text("window.DOCMAP_DATA=" + serialized + ";\n", encoding="utf-8")
    (output / "index.html").write_text(_INDEX, encoding="utf-8")


_INDEX = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>Software foundation · Edit maps</title>
  <link rel="stylesheet" href="explorer.css">
  <script src="data.js" defer></script>
  <script src="explorer.js" defer></script>
</head>
<body>
  <a class="skip-link" href="#main">Skip to content</a>
  <aside class="sidebar" aria-label="Atlas navigation">
    <a class="brand" href="#home"><span class="brand-mark" aria-hidden="true">⌘</span><span>EDIT MAPS<small id="brand-title">Software foundation</small></span></a>
    <div class="sidebar-label">EDIT & EXPLORE</div>
    <nav id="navigation"></nav>
    <div class="sidebar-foot"><span class="status-dot"></span> Local snapshot<br><small id="snapshot-date"></small><p>Generated on demand.<br>Code may have changed since.</p></div>
  </aside>
  <div class="workspace">
    <header class="topbar">
      <button class="mobile-menu" id="menu-button" type="button" aria-label="Toggle navigation" aria-expanded="false">☰</button>
      <div class="search-wrap"><label class="sr-only" for="global-search">Search files and symbols</label><span aria-hidden="true">⌕</span><input id="global-search" autocomplete="off" placeholder="Find a function, class, or file…"><kbd>/</kbd><div id="search-preview" class="search-preview" hidden></div></div>
      <button class="print-button" id="print-button" type="button">Print this view</button>
    </header>
    <main id="main" tabindex="-1"><noscript>This local atlas needs JavaScript to navigate its source snapshots. Printable PDF chapters are available in the pdf directory.</noscript></main>
    <footer class="footer"><span id="footer-title"></span><span>Static analysis · source snapshot · no runtime tracing</span></footer>
  </div>
</body>
</html>
"""
