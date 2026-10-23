"""The raw contents of a .key file: its archives (protobuf objects) and data files.

A .key file is a zip (or, for older files, a folder) holding ``Index/*.iwa``
files and a ``Data/`` folder of images and media. Each .iwa file is a stream
of Snappy-compressed chunks of protobuf "archives", each with a numeric
identifier that other archives use to refer to it. Decoding is done by
keynote-parser; this module indexes the objects by identifier and writes back
only the files that changed.
"""

from __future__ import annotations

import io
import os
import zipfile
from typing import Any, Dict, Iterator, List, Optional, Tuple, Type, Union

from keynote_parser.codec import IWAFile

PathLike = Union[str, "os.PathLike[str]"]


class Package:
    """Every file in a .key document, with its archives indexed by identifier."""

    def __init__(self, files: Dict[str, bytes]):
        self._raw = files
        self._iwa: Dict[str, IWAFile] = {}
        self._objects: Dict[int, Tuple[str, Any]] = {}
        self._dirty: set = set()
        for name, data in files.items():
            if name.endswith(".iwa"):
                iwa = IWAFile.from_buffer(data, name)
                self._iwa[name] = iwa
                for chunk in iwa.chunks:
                    for segment in chunk.archives:
                        if segment.objects:
                            self._objects[segment.header.identifier] = (name, segment.objects[0])

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
        return identifier in self._objects

    def get(self, identifier: int) -> Any:
        """The archive with this identifier."""
        return self._objects[identifier][1]

    def deref(self, ref: Any) -> Any:
        """Follow a ``TSP.Reference`` (anything with an ``identifier``) to its archive."""
        return self.get(ref.identifier)

    def file_of(self, identifier: int) -> str:
        return self._objects[identifier][0]

    def objects(self, type_name: Optional[str] = None) -> Iterator[Tuple[int, Any]]:
        """``(identifier, archive)`` pairs, optionally only those of one protobuf type, e.g. ``"KN.SlideArchive"``."""
        for identifier, (_, obj) in self._objects.items():
            if type_name is None or _type_name(obj) == type_name:
                yield identifier, obj

    def mark_changed(self, identifier: int) -> None:
        """Record that an archive was edited in place, so its file is re-encoded on save."""
        self._dirty.add(self.file_of(identifier))

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


def _type_name(obj: Any) -> str:
    descriptor = getattr(type(obj), "DESCRIPTOR", None)
    return descriptor.full_name if descriptor is not None else type(obj).__name__
