"""Presentations and slides, driven through Keynote's scripting interface."""

from __future__ import annotations

import os
from typing import Any, Dict, Iterator, List, Optional, Union

from . import _osa
from .transitions import Transition, normalize_effect

PathLike = Union[str, "os.PathLike[str]"]

# --- JXA scripts. Each defines main(Keynote, args). ---------------------------

_LIST_THEMES = """
function main(Keynote, args) { return Keynote.themes.name(); }
"""

_NEW = """
function main(Keynote, args) {
  const props = {};
  if (args.theme) props.documentTheme = Keynote.themes.byName(args.theme);
  if (args.width) props.width = args.width;
  if (args.height) props.height = args.height;
  const doc = Keynote.Document(props).make();
  return doc.id();
}
"""

_OPEN = """
function main(Keynote, args) {
  const doc = Keynote.open(Path(args.path));
  return doc.id();
}
"""

_SAVE = """
function main(Keynote, args) {
  const doc = Keynote.documents.byId(args.doc);
  if (args.path) doc.save({in: Path(args.path)});
  else doc.save();
  return null;
}
"""

_CLOSE = """
function main(Keynote, args) {
  Keynote.documents.byId(args.doc).close({saving: args.save ? "yes" : "no"});
  return null;
}
"""

_DOC_INFO = """
function main(Keynote, args) {
  const doc = Keynote.documents.byId(args.doc);
  const file = doc.file();
  return {
    name: doc.name(),
    path: file ? file.toString() : null,
    theme: doc.documentTheme().name(),
    width: doc.width(),
    height: doc.height(),
    slide_count: doc.slides.length,
  };
}
"""

_SET_THEME = """
function main(Keynote, args) {
  Keynote.documents.byId(args.doc).documentTheme = Keynote.themes.byName(args.theme);
  return null;
}
"""

# Reading every field of one slide, or of all slides, in a single call keeps
# round trips to Keynote down.
_SLIDE_READER = """
function readText(fn) {
  try { const t = fn(); return t === null || t === undefined ? null : String(t); }
  catch (e) { return null; }
}
function readSlide(s, index) {
  const tp = s.transitionProperties();
  return {
    index: index,
    title: s.titleShowing() ? readText(() => s.defaultTitleItem().objectText()) : null,
    body: s.bodyShowing() ? readText(() => s.defaultBodyItem().objectText()) : null,
    notes: readText(() => s.presenterNotes()),
    skipped: s.skipped(),
    transition: {
      effect: String(tp.transitionEffect),
      duration: tp.transitionDuration,
      delay: tp.transitionDelay,
      automatic: tp.automaticTransition,
    },
  };
}
"""

_READ_SLIDE = _SLIDE_READER + """
function main(Keynote, args) {
  const doc = Keynote.documents.byId(args.doc);
  return readSlide(doc.slides[args.index], args.index);
}
"""

_READ_ALL = _SLIDE_READER + """
function main(Keynote, args) {
  const doc = Keynote.documents.byId(args.doc);
  const out = [];
  for (let i = 0; i < doc.slides.length; i++) out.push(readSlide(doc.slides[i], i));
  return out;
}
"""

_UPDATE_SLIDE = """
function main(Keynote, args) {
  const doc = Keynote.documents.byId(args.doc);
  const s = doc.slides[args.index];
  if ("title" in args) {
    s.titleShowing = true;
    s.defaultTitleItem.objectText = args.title;
  }
  if ("body" in args) {
    s.bodyShowing = true;
    s.defaultBodyItem.objectText = args.body;
  }
  if ("notes" in args) s.presenterNotes = args.notes;
  if ("skipped" in args) s.skipped = args.skipped;
  return null;
}
"""

_DELETE_SLIDE = """
function main(Keynote, args) {
  Keynote.documents.byId(args.doc).slides[args.index].delete();
  return null;
}
"""

# --- AppleScript, for the things JXA handles badly. ---------------------------
# JXA can't read a document's master slides on Keynote 14.5 (error -1700), so
# everything to do with layouts goes through AppleScript. Layout names can
# contain commas, so lists come back one name per line.

_LAYOUT_NAMES = """
on run argv
  tell application "Keynote"
    set names to name of every master slide of document id (item 1 of argv)
  end tell
  set AppleScript's text item delimiters to linefeed
  return names as text
end run
"""

_SLIDE_LAYOUTS = """
on run argv
  set out to {}
  tell application "Keynote"
    repeat with s in slides of document id (item 1 of argv)
      set end of out to name of base slide of s
    end repeat
  end tell
  set AppleScript's text item delimiters to linefeed
  return out as text
end run
"""

_SLIDE_LAYOUT = """
on run argv
  tell application "Keynote"
    return name of base slide of slide ((item 2 of argv) as integer) of document id (item 1 of argv)
  end tell
end run
"""

_SET_LAYOUT = """
on run argv
  tell application "Keynote"
    set d to document id (item 1 of argv)
    set base slide of slide ((item 2 of argv) as integer) of d to master slide (item 3 of argv) of d
  end tell
end run
"""

_ADD_SLIDE = """
on run argv
  set docId to item 1 of argv
  set layoutName to item 2 of argv
  tell application "Keynote"
    set d to document id docId
    if layoutName is "" then
      make new slide at end of slides of d
    else
      make new slide at end of slides of d with properties {base slide:master slide layoutName of d}
    end if
    return count of slides of d
  end tell
end run
"""

_MOVE_SLIDE = """
on run argv
  set docId to item 1 of argv
  set fromIdx to (item 2 of argv) as integer
  set toIdx to (item 3 of argv) as integer
  tell application "Keynote"
    set d to document id docId
    if toIdx > fromIdx then
      move slide fromIdx of d to after slide toIdx of d
    else
      move slide fromIdx of d to before slide toIdx of d
    end if
  end tell
end run
"""

# {effect} comes from transitions.EFFECTS only; every other value is in argv.
_SET_TRANSITION = """
on run argv
  set docId to item 1 of argv
  set idx to (item 2 of argv) as integer
  tell application "Keynote"
    set s to slide idx of document id docId
    set props to {{transition effect:{effect}}}
    if item 3 of argv is not "" then set props to props & {{transition duration:(item 3 of argv) as real}}
    if item 4 of argv is not "" then set props to props & {{transition delay:(item 4 of argv) as real}}
    if item 5 of argv is not "" then set props to props & {{automatic transition:(item 5 of argv is "true")}}
    set transition properties of s to props
  end tell
end run
"""


def list_themes() -> List[str]:
    """Names of the themes installed in Keynote."""
    return _osa.jxa(_LIST_THEMES)


_SLIDE_FIELDS = frozenset({"layout", "title", "body", "notes", "skipped"})


def _check_fields(fields: Dict[str, Any]) -> None:
    unknown = set(fields) - _SLIDE_FIELDS
    if unknown:
        raise TypeError(f"Unknown slide fields: {', '.join(sorted(unknown))}")


def _lines(text: str) -> List[str]:
    return text.split("\n") if text else []


def _num(value: Optional[float]) -> str:
    # repr keeps "." as the decimal separator whatever the Mac's locale.
    return "" if value is None else repr(float(value))


class Slide:
    """One slide, addressed by its position in the presentation.

    A ``Slide`` points at a position, so after adding, deleting or moving
    slides, fetch fresh ones from :attr:`Presentation.slides`.
    """

    def __init__(self, presentation: "Presentation", index: int):
        self.presentation = presentation
        self.index = index

    def __repr__(self) -> str:
        return f"<Slide {self.index} of {self.presentation.name!r}>"

    def _args(self, **extra: Any) -> Dict[str, Any]:
        return {"doc": self.presentation.id, "index": self.index, **extra}

    def read(self) -> Dict[str, Any]:
        """Every field of the slide: layout, title, body, notes, skipped, transition."""
        data = _osa.jxa(_READ_SLIDE, **self._args())
        data["layout"] = _osa.applescript(_SLIDE_LAYOUT, self.presentation.id, str(self.index + 1))
        return data

    def update(self, **fields: Any) -> None:
        """Set several of ``layout``, ``title``, ``body``, ``notes`` and ``skipped`` at once."""
        _check_fields(fields)
        if "layout" in fields:
            # Change the layout first, so the text lands in the new layout's placeholders.
            layout = fields.pop("layout")
            _osa.applescript(_SET_LAYOUT, self.presentation.id, str(self.index + 1), layout)
        if fields:
            _osa.jxa(_UPDATE_SLIDE, **self._args(**fields))

    @property
    def title(self) -> Optional[str]:
        """Text of the title placeholder, or ``None`` if the slide shows no title."""
        return self.read()["title"]

    @title.setter
    def title(self, text: str) -> None:
        self.update(title=text)

    @property
    def body(self) -> Optional[str]:
        """Text of the body placeholder, one line per bullet, or ``None`` if not shown."""
        return self.read()["body"]

    @body.setter
    def body(self, text: str) -> None:
        self.update(body=text)

    @property
    def notes(self) -> str:
        """Presenter notes."""
        return self.read()["notes"] or ""

    @notes.setter
    def notes(self, text: str) -> None:
        self.update(notes=text)

    @property
    def layout(self) -> Optional[str]:
        """Name of the master slide (layout) the slide is based on."""
        return self.read()["layout"]

    @layout.setter
    def layout(self, name: str) -> None:
        self.update(layout=name)

    @property
    def skipped(self) -> bool:
        return bool(self.read()["skipped"])

    @skipped.setter
    def skipped(self, value: bool) -> None:
        self.update(skipped=bool(value))

    @property
    def transition(self) -> Transition:
        t = self.read()["transition"]
        return Transition(normalize_effect(t["effect"]), t["duration"], t["delay"], t["automatic"])

    def set_transition(
        self,
        effect: str,
        duration: Optional[float] = None,
        delay: Optional[float] = None,
        automatic: Optional[bool] = None,
    ) -> None:
        """Set the transition into the next slide, for example ``set_transition("dissolve", 1.0)``."""
        script = _SET_TRANSITION.format(effect=normalize_effect(effect))
        _osa.applescript(
            script,
            self.presentation.id,
            str(self.index + 1),
            _num(duration),
            _num(delay),
            "" if automatic is None else str(bool(automatic)).lower(),
        )

    def delete(self) -> None:
        _osa.jxa(_DELETE_SLIDE, **self._args())

    def move_to(self, index: int) -> None:
        """Move this slide so that it ends up at ``index``."""
        target = self.presentation._normalize_index(index)
        if target != self.index:
            _osa.applescript(_MOVE_SLIDE, self.presentation.id, str(self.index + 1), str(target + 1))
            self.index = target


class Presentation:
    """An open Keynote document.

    Create one with :meth:`new` or :meth:`open`. It can be used as a context
    manager, which closes the document without saving on exit.
    """

    def __init__(self, doc_id: str):
        self.id = doc_id

    @classmethod
    def new(
        cls,
        theme: Optional[str] = None,
        path: Optional[PathLike] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> "Presentation":
        """Create a presentation, optionally with a theme and slide size, and save it to ``path``."""
        pres = cls(_osa.jxa(_NEW, theme=theme, width=width, height=height))
        if path is not None:
            pres.save(path)
        return pres

    @classmethod
    def open(cls, path: PathLike) -> "Presentation":
        """Open an existing ``.key`` file."""
        full = os.path.abspath(os.fspath(path))
        if not os.path.exists(full):
            raise FileNotFoundError(full)
        return cls(_osa.jxa(_OPEN, path=full))

    def __enter__(self) -> "Presentation":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"<Presentation {self.name!r}>"

    def info(self) -> Dict[str, Any]:
        """Name, file path, theme, size and slide count in one call."""
        return _osa.jxa(_DOC_INFO, doc=self.id)

    @property
    def name(self) -> str:
        return self.info()["name"]

    @property
    def path(self) -> Optional[str]:
        return self.info()["path"]

    @property
    def theme(self) -> str:
        return self.info()["theme"]

    @theme.setter
    def theme(self, name: str) -> None:
        _osa.jxa(_SET_THEME, doc=self.id, theme=name)

    @property
    def layouts(self) -> List[str]:
        """Names of the master slides available in this presentation's theme."""
        return _lines(_osa.applescript(_LAYOUT_NAMES, self.id))

    def __len__(self) -> int:
        return self.info()["slide_count"]

    def _normalize_index(self, index: int) -> int:
        count = len(self)
        if index < 0:
            index += count
        if not 0 <= index < count:
            raise IndexError(f"slide index {index} out of range for {count} slides")
        return index

    def __getitem__(self, index: int) -> Slide:
        return Slide(self, self._normalize_index(index))

    def __iter__(self) -> Iterator[Slide]:
        return iter(self.slides)

    @property
    def slides(self) -> List[Slide]:
        return [Slide(self, i) for i in range(len(self))]

    def read_slides(self) -> List[Dict[str, Any]]:
        """Every field of every slide."""
        rows = _osa.jxa(_READ_ALL, doc=self.id)
        for row, layout in zip(rows, _lines(_osa.applescript(_SLIDE_LAYOUTS, self.id))):
            row["layout"] = layout
        return rows

    def add_slide(
        self,
        layout: Optional[str] = None,
        index: Optional[int] = None,
        **fields: Any,
    ) -> Slide:
        """Add a slide, at the end unless ``index`` is given.

        ``fields`` can be ``title``, ``body``, ``notes`` or ``skipped``.
        """
        _check_fields(fields)
        count = int(_osa.applescript(_ADD_SLIDE, self.id, layout or ""))
        slide = Slide(self, count - 1)
        slide.update(**fields)
        if index is not None:
            slide.move_to(index)
        return slide

    def save(self, path: Optional[PathLike] = None) -> None:
        """Save in place, or to ``path`` (always as a ``.key`` file)."""
        full = None
        if path is not None:
            full = os.path.abspath(os.fspath(path))
            if not full.endswith(".key"):
                full += ".key"
        _osa.jxa(_SAVE, doc=self.id, path=full)

    def close(self, save: bool = False) -> None:
        _osa.jxa(_CLOSE, doc=self.id, save=save)
