"""A small driver for real Keynote, for the integration tests only.

It opens a deck, reads back what Keynote shows and saves Keynote's own copy,
so tests can check that files written by pykeynote work in the real app.
Values are never pasted into script source: JXA gets its arguments as one
JSON string and returns JSON, and AppleScript gets them through ``argv``.

Keynote is found by bundle id, ``com.apple.iWork.Keynote`` unless
``PYKEYNOTE_KEYNOTE_ID`` names another (``com.apple.Keynote`` is Keynote
Creator Studio).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Any, Dict, List

BUNDLE_ID = os.environ.get("PYKEYNOTE_KEYNOTE_ID", "com.apple.iWork.Keynote")
if not re.fullmatch(r"[A-Za-z0-9.-]+", BUNDLE_ID):
    raise ValueError(f"not a bundle id: {BUNDLE_ID!r}")


class KeynoteError(RuntimeError):
    """Keynote or osascript reported an error."""


def _run(language: str, script: str, argv: List[str]) -> str:
    proc = subprocess.run(["osascript", "-l", language, "-", *argv], input=script, capture_output=True, text=True)
    if proc.returncode != 0:
        raise KeynoteError(proc.stderr.strip() or f"osascript exited with {proc.returncode}")
    return proc.stdout.strip()


def jxa(script: str, **args: Any) -> Any:
    """Run JXA that defines ``function main(Keynote, args)``."""
    wrapper = f"""
function run(argv) {{
  const Keynote = Application("{BUNDLE_ID}");
  const result = main(Keynote, JSON.parse(argv[0]));
  return JSON.stringify(result === undefined ? null : result);
}}
"""
    out = _run("JavaScript", script + wrapper, [json.dumps(args)])
    return json.loads(out) if out else None


def applescript(script: str, *args: str) -> str:
    """Run AppleScript with an ``on run argv`` handler. ``KEYNOTE`` in it stands for the app."""
    return _run("AppleScript", script.replace("KEYNOTE", f'application id "{BUNDLE_ID}"'), list(args))


# Opening sometimes never replies unless Keynote is activated first.
_OPEN = """
function main(Keynote, args) {
  Keynote.activate();
  return Keynote.open(Path(args.path)).id();
}
"""

_INFO = """
function main(Keynote, args) {
  const doc = Keynote.documents.byId(args.doc);
  return {theme: doc.documentTheme().name(), width: doc.width(), height: doc.height(), slide_count: doc.slides.length};
}
"""

_READ_SLIDES = """
function readText(fn) {
  try { const t = fn(); return t === null || t === undefined ? null : String(t); }
  catch (e) { return null; }
}
function main(Keynote, args) {
  const doc = Keynote.documents.byId(args.doc);
  const out = [];
  for (let i = 0; i < doc.slides.length; i++) {
    const s = doc.slides[i];
    out.push({
      title: s.titleShowing() ? readText(() => s.defaultTitleItem().objectText()) : null,
      body: s.bodyShowing() ? readText(() => s.defaultBodyItem().objectText()) : null,
      notes: readText(() => s.presenterNotes()),
      skipped: s.skipped(),
    });
  }
  return out;
}
"""

# JXA can't read master slides on Keynote 14.5 (error -1700), so layouts come
# from AppleScript, one name per line since names can hold commas.
_LAYOUTS = """
on run argv
  set out to {}
  tell KEYNOTE
    repeat with s in slides of document id (item 1 of argv)
      set end of out to name of base slide of s
    end repeat
  end tell
  set AppleScript's text item delimiters to linefeed
  return out as text
end run
"""

_SAVE = """
function main(Keynote, args) {
  Keynote.documents.byId(args.doc).save({in: Path(args.path)});
  return null;
}
"""

_CLOSE = """
function main(Keynote, args) {
  Keynote.documents.byId(args.doc).close({saving: "no"});
  return null;
}
"""


class Document:
    """A deck open in Keynote."""

    def __init__(self, path: "os.PathLike[str] | str"):
        self.id = jxa(_OPEN, path=os.path.abspath(os.fspath(path)))

    def info(self) -> Dict[str, Any]:
        """Theme, width, height and slide count."""
        return jxa(_INFO, doc=self.id)

    @property
    def theme(self) -> str:
        return self.info()["theme"]

    def __len__(self) -> int:
        return self.info()["slide_count"]

    def read_slides(self) -> List[Dict[str, Any]]:
        """Each slide's layout, title, body, notes and skipped flag, as Keynote shows them."""
        rows = jxa(_READ_SLIDES, doc=self.id)
        layouts = applescript(_LAYOUTS, self.id)
        for row, layout in zip(rows, layouts.split("\n") if layouts else []):
            row["layout"] = layout
        return rows

    def save(self, path: "os.PathLike[str] | str") -> None:
        """Have Keynote save its own copy to ``path``."""
        jxa(_SAVE, doc=self.id, path=os.path.abspath(os.fspath(path)))

    def close(self) -> None:
        jxa(_CLOSE, doc=self.id)
