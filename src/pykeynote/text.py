"""Reading and rewriting the text in a Keynote text storage (``TSWP.StorageArchive``).

A storage keeps its text as one string, with paragraphs ended by ``\\r``.
Formatting lives in attribute tables, lists of ``(character_index, value)``
entries where each value holds until the next entry. Character indexes count
UTF-16 code units, as in Objective-C strings, not Python characters.

Keynote expects some tables to change only at paragraph starts, and
``table_para_style`` to hold exactly one entry per paragraph. Getting these
wrong can make Keynote draw a text box 2^16 points tall or crash, so
:meth:`Text.set_paragraphs` rebuilds them all.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, List, Optional, Sequence, Union

PARAGRAPH = "\r"  # end of paragraph
LINE_BREAK = " "  # line break inside a paragraph (shift-return)
ATTACHMENT = "￼"  # stands in for an inline object, such as an image

# Tables whose runs start at paragraph boundaries. table_para_style is
# handled separately, because it needs an entry for every paragraph.
_PARAGRAPH_TABLES = (
    "table_para_data",
    "table_list_style",
    "table_para_starts",
    "table_para_bidi",
    "table_drop_cap_style",
    "table_layout_style",
)

# Tables of character runs. New text takes on the formatting of the start of
# the old text.
_CHARACTER_TABLES = (
    "table_char_style",
    "table_language",
    "table_dictation",
    "table_highlight",
    "table_insertion",
    "table_deletion",
    "table_bookmark",
    "table_rubyfield",
    "table_tatechuyoko",
    "table_section",
)

# Tables that tie objects to particular characters. Rewriting text that has
# any of these would leave them pointing at the wrong place.
_ANCHORED_TABLES = (
    "table_attachment",
    "table_smartfield",
    "table_footnote",
    "table_overlapping_highlight",
    "table_pencil_annotation",
)


class UnsupportedTextError(ValueError):
    """The text holds something pykeynote can't rewrite safely yet, such as an inline image."""


@dataclass(frozen=True)
class Paragraph:
    """One paragraph of text. ``level`` is the list indent level, from 0."""

    text: str
    level: int = 0
    bulleted: bool = False


ParagraphInput = Union[str, Paragraph]


def utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


class Text:
    """The text in one storage archive."""

    def __init__(self, package: Any, identifier: int):
        self._package = package
        self.identifier = identifier
        self._storage = package.get(identifier)

    @property
    def raw(self) -> str:
        return "".join(self._storage.text)

    def __str__(self) -> str:
        return "\n".join(p.text for p in self.paragraphs)

    def _starts(self, chunks: Sequence[str]) -> List[int]:
        starts, offset = [], 0
        for chunk in chunks:
            starts.append(offset)
            offset += utf16_len(chunk) + 1
        return starts

    @property
    def paragraphs(self) -> List[Paragraph]:
        raw = self.raw
        if not raw:
            return []
        chunks = raw.split(PARAGRAPH)
        out = []
        for chunk, start in zip(chunks, self._starts(chunks)):
            level = _active(self._storage.table_para_data.entries, start)
            list_style = _active(self._storage.table_list_style.entries, start)
            out.append(
                Paragraph(
                    chunk.replace(ATTACHMENT, "").replace(LINE_BREAK, "\n"),
                    level=level.first if level is not None else 0,
                    bulleted=self._is_bulleted(list_style),
                )
            )
        return out

    def _is_bulleted(self, entry: Any) -> bool:
        if entry is None or not entry.HasField("object"):
            return False
        style = self._package.deref(entry.object)
        return bool(getattr(style, "strings", None)) or any(t != 0 for t in getattr(style, "label_types", []))

    def set_paragraphs(self, paragraphs: Iterable[ParagraphInput]) -> None:
        """Replace the text, keeping the formatting.

        Each item is a string or a :class:`Paragraph`. A string keeps the
        indent level of the paragraph it replaces; a ``Paragraph`` sets its
        own. New paragraphs beyond the old count copy the formatting of the
        old last paragraph. A ``"\\n"`` inside a paragraph becomes a line break.
        ``bulleted`` is ignored for now, since bullets come from the layout.
        """
        st = self._storage
        new = [p if isinstance(p, Paragraph) else Paragraph(p, level=-1) for p in paragraphs]
        for p in new:
            if PARAGRAPH in p.text or ATTACHMENT in p.text:
                raise ValueError(f"paragraph text can't contain {PARAGRAPH!r} or {ATTACHMENT!r}: {p.text!r}")
        for name in _ANCHORED_TABLES:
            if st.HasField(name) and len(getattr(st, name).entries) > 0:
                raise UnsupportedTextError(
                    f"this text holds inline objects or annotations ({name}), which can't be rewritten yet"
                )

        old_chunks = self.raw.split(PARAGRAPH) if self.raw else [""]
        old_starts = self._starts(old_chunks)
        texts = [p.text.replace("\n", LINE_BREAK) for p in new] or [""]
        new_starts = self._starts(texts)

        def source(j: int) -> int:
            return min(j, len(old_starts) - 1)

        # One table_para_style entry per paragraph.
        if st.HasField("table_para_style"):
            table = st.table_para_style
            old = list(table.entries)
            entries = []
            for j, start in enumerate(new_starts):
                src = _exact(old, old_starts[source(j)]) or _active(old, old_starts[source(j)])
                entries.append(_copy_entry(src, start))
            _replace_entries(table, entries)

        for name in _PARAGRAPH_TABLES:
            if not st.HasField(name):
                continue
            table = getattr(st, name)
            old = list(table.entries)
            if not old:
                continue
            entries = []
            for j, start in enumerate(new_starts):
                src = _active(old, old_starts[source(j)])
                if src is None:
                    continue
                entry = _copy_entry(src, start)
                if name == "table_para_data" and j < len(new) and new[j].level >= 0:
                    entry.first = new[j].level
                if not entries or _value_key(entries[-1]) != _value_key(entry):
                    entries.append(entry)
            _replace_entries(table, entries)

        for name in _CHARACTER_TABLES:
            if not st.HasField(name):
                continue
            table = getattr(st, name)
            first = _active(list(table.entries), 0)
            _replace_entries(table, [_copy_entry(first, 0)] if first is not None else [])

        del st.text[:]
        joined = PARAGRAPH.join(texts)
        if joined:
            st.text.append(joined)
        self._package.mark_changed(self.identifier)


def _active(entries: Sequence[Any], index: int) -> Optional[Any]:
    """The table entry in force at ``index``."""
    current = None
    for e in entries:
        if e.character_index > index:
            break
        current = e
    return current


def _exact(entries: Sequence[Any], index: int) -> Optional[Any]:
    for e in entries:
        if e.character_index == index:
            return e
    return None


def _copy_entry(entry: Any, index: int) -> Any:
    copy = type(entry)()
    copy.CopyFrom(entry)
    copy.character_index = index
    return copy


def _value_key(entry: Any) -> bytes:
    probe = type(entry)()
    probe.CopyFrom(entry)
    probe.character_index = 0
    return probe.SerializeToString()


def _replace_entries(table: Any, entries: List[Any]) -> None:
    del table.entries[:]
    for e in entries:
        table.entries.add().CopyFrom(e)
