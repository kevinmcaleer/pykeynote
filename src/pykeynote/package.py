"""The raw contents of a .key file: its archives (protobuf objects) and data files.

A .key file is a zip (or, for older files, a folder) holding ``Index/*.iwa``
files and a ``Data/`` folder of images and media. Each .iwa file is a stream
of Snappy-compressed chunks of protobuf "archives", each with a numeric
identifier that other archives use to refer to it. Decoding is done by
keynote-parser; this module indexes the objects by identifier and writes back
only the files that changed.

Each .iwa file is a "component", listed in the ``TSP.PackageMetadata`` archive
in ``Index/Metadata.iwa``. A component records which other components it
refers to and the UUID of each of its objects. Each archive's header lists
the identifiers its object refers to. Structural edits, such as adding or
removing slides, have to keep all of these in step.
"""

from __future__ import annotations

import io
import os
import uuid as uuidlib
import zipfile
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple, Union

from keynote_parser.codec import IWACompressedChunk, IWAFile

PathLike = Union[str, "os.PathLike[str]"]

METADATA_FILE = "Index/Metadata.iwa"
METADATA_ID = 2


class Package:
    """Every file in a .key document, with its archives indexed by identifier."""

    def __init__(self, files: Dict[str, bytes]):
        self._raw = files
        self._iwa: Dict[str, IWAFile] = {}
        self._segments: Dict[int, Tuple[str, Any]] = {}
        self._dirty: set = set()
        for name, data in files.items():
            if name.endswith(".iwa"):
                self._index_file(name, IWAFile.from_buffer(data, name))

    def _index_file(self, name: str, iwa: IWAFile) -> None:
        self._iwa[name] = iwa
        for chunk in iwa.chunks:
            for segment in chunk.archives:
                if segment.objects:
                    self._segments[segment.header.identifier] = (name, segment)

    @classmethod
    def open(cls, path: PathLike) -> "Package":
        path = os.fspath(path)
        files: Dict[str, bytes] = {}
        if os.path.isdir(path):
            for root, _, names in os.walk(path):
                for n in names:
                    full = os.path.join(root, n)
                    with open(full, "rb") as fh:
                        files[os.path.relpath(full, path).replace(os.sep, "/")] = fh.read()
        else:
            with zipfile.ZipFile(path) as z:
                for info in z.infolist():
                    if not info.is_dir():
                        files[info.filename] = z.read(info)
        return cls(files)

    # --- objects --------------------------------------------------------------

    def __contains__(self, identifier: int) -> bool:
        return identifier in self._segments

    def get(self, identifier: int) -> Any:
        """The archive with this identifier."""
        return self._segments[identifier][1].objects[0]

    def deref(self, ref: Any) -> Any:
        """Follow a ``TSP.Reference`` (anything with an ``identifier``) to its archive."""
        return self.get(ref.identifier)

    def file_of(self, identifier: int) -> str:
        return self._segments[identifier][0]

    def segment(self, identifier: int) -> Any:
        return self._segments[identifier][1]

    def objects(self, type_name: Optional[str] = None) -> Iterator[Tuple[int, Any]]:
        """``(identifier, archive)`` pairs, optionally only those of one protobuf type, e.g. ``"KN.SlideArchive"``."""
        for identifier, (_, segment) in self._segments.items():
            obj = segment.objects[0]
            if type_name is None or type_name_of(obj) == type_name:
                yield identifier, obj

    def ids_in_file(self, name: str) -> List[int]:
        return [seg.header.identifier for chunk in self._iwa[name].chunks for seg in chunk.archives if seg.objects]

    def mark_changed(self, identifier: int) -> None:
        """Record that an archive was edited in place, so its file is re-encoded on save."""
        self._dirty.add(self.file_of(identifier))

    def new_identifier(self) -> int:
        meta = self.metadata
        meta.last_object_identifier += 1
        self.mark_changed(METADATA_ID)
        return meta.last_object_identifier

    def add_object_reference(self, owner: int, target: int) -> None:
        refs = self.segment(owner).header.message_infos[0].object_references
        if target not in refs:
            refs.append(target)
            self.mark_changed(owner)

    def remove_object_reference(self, owner: int, target: int) -> None:
        refs = self.segment(owner).header.message_infos[0].object_references
        if target in refs:
            kept = [r for r in refs if r != target]
            del refs[:]
            refs.extend(kept)
            self.mark_changed(owner)

    def add_segment(self, name: str, segment: Any) -> None:
        """Append an archive segment to an existing .iwa file."""
        self._iwa[name].chunks.append(IWACompressedChunk([segment]))
        self._segments[segment.header.identifier] = (name, segment)
        self._dirty.add(name)

    def remove_segment(self, identifier: int) -> None:
        name, segment = self._segments.pop(identifier)
        for chunk in self._iwa[name].chunks:
            if segment in chunk.archives:
                chunk.archives.remove(segment)
        self._iwa[name].chunks = [c for c in self._iwa[name].chunks if c.archives]
        self._dirty.add(name)

    # --- components -----------------------------------------------------------

    @property
    def metadata(self) -> Any:
        """The ``TSP.PackageMetadata`` archive."""
        return self.get(METADATA_ID)

    def component(self, identifier: int) -> Any:
        for c in self.metadata.components:
            if c.identifier == identifier:
                return c
        raise KeyError(identifier)

    def component_for_file(self, name: str) -> Any:
        locator = name[len("Index/"):-len(".iwa")]
        for c in self.metadata.components:
            if c.locator == locator or (not c.locator and c.preferred_locator == locator):
                return c
        raise KeyError(name)

    def add_file(self, name: str, iwa: IWAFile) -> None:
        self._raw[name] = b""
        self._index_file(name, iwa)
        self._dirty.add(name)

    def remove_file(self, name: str) -> None:
        for identifier in self.ids_in_file(name):
            self._segments.pop(identifier, None)
        self._iwa.pop(name, None)
        self._raw.pop(name, None)
        self._dirty.discard(name)

    def remove_component(self, identifier: int) -> None:
        """Remove a component's entry and every other component's references to it."""
        meta = self.metadata
        kept = [c for c in meta.components if c.identifier != identifier]
        del meta.components[:]
        for c in kept:
            refs = [e for e in c.external_references if e.component_identifier != identifier]
            if len(refs) != len(c.external_references):
                del c.external_references[:]
                for e in refs:
                    c.external_references.add().CopyFrom(e)
            meta.components.add().CopyFrom(c)
        self.mark_changed(METADATA_ID)

    # --- data files -----------------------------------------------------------

    @property
    def filenames(self) -> List[str]:
        return sorted(self._raw)

    def read_file(self, name: str) -> bytes:
        return self._raw[name]

    # --- saving ---------------------------------------------------------------

    def to_bytes(self) -> bytes:
        buf = io.BytesIO()
        # Keynote writes .key zips uncompressed; the .iwa files are already compressed.
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
            for name in sorted(self._raw):
                data = self._iwa[name].to_buffer() if name in self._dirty else self._raw[name]
                z.writestr(name, data)
        return buf.getvalue()

    def save(self, path: PathLike) -> None:
        data = self.to_bytes()
        with open(path, "wb") as fh:
            fh.write(data)


def type_name_of(obj: Any) -> str:
    descriptor = getattr(type(obj), "DESCRIPTOR", None)
    return descriptor.full_name if descriptor is not None else type(obj).__name__


def _is_repeated(field: Any) -> bool:
    # protobuf 6 replaced FieldDescriptor.label with is_repeated.
    if hasattr(field, "is_repeated"):
        return field.is_repeated
    return field.label == field.LABEL_REPEATED


def walk_messages(message: Any, visit: Callable[[Any], None]) -> None:
    """Call ``visit`` on ``message`` and on every protobuf message nested inside it."""
    if not hasattr(message, "ListFields"):
        return
    visit(message)
    for field, value in message.ListFields():
        if field.type != field.TYPE_MESSAGE:
            continue
        if _is_repeated(field):
            if field.message_type.GetOptions().map_entry:
                for v in value.values():
                    walk_messages(v, visit)
            else:
                for v in value:
                    walk_messages(v, visit)
        else:
            walk_messages(value, visit)


def remap_references(message: Any, id_map: Dict[int, int]) -> None:
    """Point every ``TSP.Reference`` inside ``message`` at its new identifier."""

    def visit(m: Any) -> None:
        if m.DESCRIPTOR.full_name == "TSP.Reference" and m.identifier in id_map:
            m.identifier = id_map[m.identifier]

    walk_messages(message, visit)


def remap_uuids(message: Any, uuid_map: Dict[Tuple[int, int], Tuple[int, int]]) -> None:
    """Give every ``TSP.UUID`` inside ``message`` a fresh value, consistently across calls."""

    def visit(m: Any) -> None:
        if m.DESCRIPTOR.full_name == "TSP.UUID":
            key = (m.lower, m.upper)
            if key not in uuid_map:
                uuid_map[key] = new_uuid_parts()
            m.lower, m.upper = uuid_map[key]

    walk_messages(message, visit)


def new_uuid_parts() -> Tuple[int, int]:
    value = uuidlib.uuid4().int
    return value & 0xFFFFFFFFFFFFFFFF, value >> 64


def references_in(message: Any) -> Iterable[int]:
    found: List[int] = []

    def visit(m: Any) -> None:
        if m.DESCRIPTOR.full_name == "TSP.Reference":
            found.append(m.identifier)

    walk_messages(message, visit)
    return found
