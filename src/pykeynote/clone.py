"""Copy a drawable, with everything it owns, from one .key package into a slide of another.

Charts and tables are too intricate to write from nothing, so new ones are
copied from a small deck that Keynote made (``templates/parts/``) and then
given their own data. A drawable's objects can live in several places: the
slide's own component file, ``Index/ObjectContainer.iwa`` (chart settings),
``Index/CalculationEngine.iwa`` (table models) and components of their own
(a table's cell tiles and string lists). Each copied object gets a new
identifier in the same kind of place in the target package.

Styles are not copied. The drawable keeps using the target theme's styles
of the same name (every theme names its styles, e.g. ``chart-0-series_2``),
and its theme preset becomes the target theme's preset at the same
position. UUIDs inside the copied objects are replaced consistently, so a
copy never shares an identity with its source or with another copy.
"""

from __future__ import annotations

import copy
import re
import uuid as uuidlib
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from keynote_parser.codec import IWAArchiveSegment, IWAFile

from .drawables import STYLESHEET_FILE, add_external_reference, named_styles, stylesheet_id
from .package import METADATA_ID, Package, new_uuid_parts, references_in, remap_references, type_name_of, walk_messages

OBJECT_CONTAINER_FILE = "Index/ObjectContainer.iwa"
CALC_ENGINE_FILE = "Index/CalculationEngine.iwa"
DOCUMENT_FILE = "Index/Document.iwa"

_SHARED_FILES = (OBJECT_CONTAINER_FILE, CALC_ENGINE_FILE)
_PRESET_LISTS = ("chart_presets", "table_style_presets")
_UUID_STRING = re.compile(r"^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$")


def theme_presets(package: Package) -> Dict[str, List[int]]:
    """Identifiers of the theme's chart and table presets, by list name."""
    show = package.get(package.get(1).show.identifier)
    theme = package.deref(show.theme).super
    out: Dict[str, List[int]] = {}
    for field, value in theme.ListFields():
        if not field.is_extension:
            continue
        for name in _PRESET_LISTS:
            if name in value.DESCRIPTOR.fields_by_name:
                out[name] = [r.identifier for r in getattr(value, name)]
    return out


def _preset_map(src: Package, dst: Package) -> Dict[int, int]:
    s, d = theme_presets(src), theme_presets(dst)
    out: Dict[int, int] = {}
    for name, ids in s.items():
        targets = d.get(name, [])
        for i, identifier in enumerate(ids):
            if i < len(targets):
                out[identifier] = targets[i]
    return out


class UUIDMap:
    """New values for the UUIDs in copied objects, the same new value each time an old one is met.

    Keynote numbers related formula owners as one base UUID plus a small
    offset, so UUIDs within ``family_span`` of one already mapped keep that
    offset from its new value.
    """

    def __init__(self, family_span: int = 4096):
        self.map: Dict[int, int] = {}
        self.span = family_span

    def __call__(self, value: int) -> int:
        if value in self.map:
            return self.map[value]
        if value < 1 << 16:  # well-known owners such as 666, not real UUIDs
            return value
        for old, new in self.map.items():
            delta = value - old
            if (old >> 64) == (value >> 64) and abs(delta) < self.span:
                self.map[value] = new + delta
                return self.map[value]
        lower, upper = new_uuid_parts()
        self.map[value] = (upper << 64) | (lower & ~0xFFFF) | 0x8000
        return self.map[value]


def remap_uuids(message: Any, uuids: UUIDMap, strings: Dict[str, str]) -> None:
    def visit(m: Any) -> None:
        name = m.DESCRIPTOR.full_name
        if name == "TSP.UUID":
            if m.HasField("lower") or m.HasField("upper"):
                new = uuids((m.upper << 64) | m.lower)
                m.lower, m.upper = new & 0xFFFFFFFFFFFFFFFF, new >> 64
        elif name == "TSP.CFUUIDArchive":
            fields = ("uuid_w0", "uuid_w1", "uuid_w2", "uuid_w3")
            if any(m.HasField(f) for f in fields):
                value = sum(getattr(m, f) << (32 * i) for i, f in enumerate(fields))
                new = uuids(value)
                for i, f in enumerate(fields):
                    setattr(m, f, (new >> (32 * i)) & 0xFFFFFFFF)
        for field, value in m.ListFields():
            if field.type == field.TYPE_STRING and not _is_repeated(field) and _UUID_STRING.match(value):
                # A UUID written out, such as a table's table_id. Its bytes are the same UUID as
                # the CFUUID form (w0 first, little-endian), so it maps the same way.
                if value not in strings:
                    new = uuids(int.from_bytes(uuidlib.UUID(value).bytes, "little"))
                    strings[value] = str(uuidlib.UUID(bytes=new.to_bytes(16, "little"))).upper()
                setattr(m, field.name, strings[value])

    walk_messages(message, visit)


def _is_repeated(field: Any) -> bool:
    if hasattr(field, "is_repeated"):
        return field.is_repeated
    return field.label == field.LABEL_REPEATED


def _header_refs(package: Package, identifier: int) -> List[int]:
    return list(package.segment(identifier).header.message_infos[0].object_references)


class Importer:
    """Copies drawables from ``src`` into ``dst``. One importer can copy several drawables."""

    def __init__(
        self,
        src: Package,
        dst: Package,
        rename: Optional[Callable[[str], str]] = None,
        presets: Optional[Dict[int, int]] = None,
    ):
        """``rename`` maps a source style name to the target style to use instead, and
        ``presets`` a source preset to a target preset; by default both keep their name or position."""
        self.src = src
        self.dst = dst
        src_styles = named_styles(src)
        dst_styles = named_styles(dst)
        self.fixed: Dict[int, int] = {}  # source objects that stand for an existing target object
        for name, identifier in src_styles.items():
            target = rename(name) if rename else name
            if target in dst_styles:
                self.fixed[identifier] = dst_styles[target]
        self.fixed[stylesheet_id(src)] = stylesheet_id(dst)
        self.fixed.update(_preset_map(src, dst))
        self.fixed.update(presets or {})
        self.keep_uuids = False  # for experiments: copy UUIDs unchanged
        self.src_style_ids = set(src.ids_in_file(STYLESHEET_FILE))

    def closure(self, root: int, stop: Set[int]) -> List[int]:
        """Every object ``root`` owns: what it refers to, short of styles, presets and ``stop``."""
        seen: List[int] = []
        found: Set[int] = set()
        todo = [root]
        while todo:
            i = todo.pop(0)
            if i in found or i in stop or i in self.fixed:
                continue
            if i in self.src_style_ids:
                name = type_name_of(self.src.get(i))
                raise ValueError(f"can't copy: the target theme has no style matching {name} {i}")
            if self.src.file_of(i) == DOCUMENT_FILE:
                raise ValueError(f"can't copy: the drawable refers to document object {i}")
            found.add(i)
            seen.append(i)
            todo.extend(_header_refs(self.src, i))
        return seen

    def copy_drawable(self, root: int, src_slide_id: int, dst_slide_id: int, extra: Optional[List[int]] = None) -> Dict[int, int]:
        """Copy ``root`` (and ``extra`` objects it needs but doesn't refer to) onto the target slide.

        Returns the map from source to new identifiers. The caller puts the
        new root on the slide.
        """
        src, dst = self.src, self.dst
        src_slide_file = src.file_of(src_slide_id)
        dst_slide_file = dst.file_of(dst_slide_id)
        ids = self.closure(root, {src_slide_id})
        for i in extra or []:
            for j in self.closure(i, {src_slide_id} | set(ids)):
                ids.append(j)

        id_map: Dict[int, int] = {i: dst.new_identifier() for i in ids}
        ref_map = dict(self.fixed)
        ref_map[src_slide_id] = dst_slide_id
        ref_map.update(id_map)

        uuids = UUIDMap()
        strings: Dict[str, str] = {}
        new_components: Dict[str, Tuple[str, Any]] = {}  # source file -> (target file, component)

        placed: List[Tuple[str, int]] = []
        for i in ids:
            src_file = src.file_of(i)
            if src_file == src_slide_file:
                dst_file = dst_slide_file
            elif src_file in _SHARED_FILES:
                dst_file = src_file
                self._ensure_shared_file(dst_file)
            else:
                dst_file = self._new_component_file(src_file, i, id_map, new_components)
            segment = src.segment(i)
            header = copy.deepcopy(segment.header)
            header.identifier = id_map[i]
            for info in header.message_infos:
                refs = [ref_map.get(r, r) for r in info.object_references]
                del info.object_references[:]
                info.object_references.extend(refs)
                del info.data_references[:]
            objects = []
            for obj in segment.objects:
                if hasattr(obj, "ListFields"):
                    obj = copy.deepcopy(obj)
                    remap_references(obj, ref_map)
                    if not self.keep_uuids:
                        remap_uuids(obj, uuids, strings)
                objects.append(obj)
            dst.add_segment(dst_file, IWAArchiveSegment(header, objects))
            placed.append((dst_file, id_map[i]))
            if dst_file == OBJECT_CONTAINER_FILE:
                container = dst.get(self._container_id())
                container.objects.add().identifier = id_map[i]
                dst.mark_changed(self._container_id())

        # Component bookkeeping: UUIDs for objects Keynote tracks, and references between components.
        for i in ids:
            src_component = src.component_for_file(src.file_of(i))
            dst_component = dst.component_for_file(dst.file_of(id_map[i]))
            for e in src_component.object_uuid_map_entries:
                if e.identifier == i:
                    added = dst_component.object_uuid_map_entries.add()
                    added.identifier = id_map[i]
                    added.uuid.lower, added.uuid.upper = new_uuid_parts()
        for dst_file, identifier in placed:
            component = dst.component_for_file(dst_file)
            strong = set(_header_refs(dst, identifier))
            for target in strong:
                if target in dst:
                    add_external_reference(dst, component, target)
            for target in set(references_in(dst.get(identifier))) - strong:
                if target in dst and target != identifier:
                    add_external_reference(dst, component, target, weak=True)
        dst.mark_changed(METADATA_ID)
        return id_map

    # --- target files ---------------------------------------------------------

    def _container_id(self) -> int:
        return self.dst.component_for_file(OBJECT_CONTAINER_FILE).identifier

    def _ensure_shared_file(self, name: str) -> None:
        dst = self.dst
        if name in dst._iwa:
            return
        if name != OBJECT_CONTAINER_FILE:
            raise ValueError(f"the target deck has no {name}")
        # Make an empty object container like the source's.
        src_component = self.src.component_for_file(name)
        identifier = dst.new_identifier()
        container_id = src_component.identifier
        header = copy.deepcopy(self.src.segment(container_id).header)
        header.identifier = identifier
        container = type(self.src.get(container_id))()
        container.identifier = 1
        dst.add_file(name, IWAFile([]))
        dst.add_segment(name, IWAArchiveSegment(header, [container]))
        component = dst.metadata.components.add()
        component.CopyFrom(src_component)
        component.identifier = identifier
        for field in ("external_references", "object_uuid_map_entries", "data_references"):
            component.ClearField(field)
        dst.mark_changed(METADATA_ID)

    def _new_component_file(self, src_file: str, identifier: int, id_map: Dict[int, int], made: Dict[str, Tuple[str, Any]]) -> str:
        if src_file in made:
            return made[src_file][0]
        src_component = self.src.component_for_file(src_file)
        if src_component.identifier != identifier:
            raise ValueError(f"can't copy object {identifier}: it shares {src_file} with objects that aren't being copied")
        new_id = id_map[identifier]
        locator = f"{src_component.preferred_locator}-{new_id}"
        name = f"Index/{locator}.iwa"
        self.dst.add_file(name, IWAFile([]))
        component = self.dst.metadata.components.add()
        component.CopyFrom(src_component)
        component.identifier = new_id
        component.locator = locator
        for field in ("external_references", "object_uuid_map_entries", "data_references"):
            component.ClearField(field)
        self.dst.mark_changed(METADATA_ID)
        made[src_file] = (name, component)
        return name


def owned_objects(package: Package, root: int, stop: Set[int]) -> List[int]:
    """``root`` and every object it owns, short of styles, document objects and ``stop``."""
    styles = set(package.ids_in_file(STYLESHEET_FILE))
    out: List[int] = []
    found: Set[int] = set()
    todo = [root]
    while todo:
        i = todo.pop(0)
        if i in found or i in stop or i in styles or i not in package:
            continue
        if package.file_of(i) == DOCUMENT_FILE:
            continue
        found.add(i)
        out.append(i)
        todo.extend(_header_refs(package, i))
    return out


def remove_objects(package: Package, ids: List[int]) -> None:
    """Delete objects, with their files if they had components of their own, and every record of them."""
    gone = set(ids)
    engine_file = CALC_ENGINE_FILE
    if engine_file in package._iwa:
        engine_id = package.component_for_file(engine_file).identifier
        tracker = package.get(engine_id).dependency_tracker
        removed_owners = {package.get(i).internal_formula_owner_id for i in ids if type_name_of(package.get(i)) == "TSCE.FormulaOwnerDependenciesArchive"}
        if removed_owners:
            kept = [r.identifier for r in tracker.formula_owner_dependencies if r.identifier not in gone]
            del tracker.formula_owner_dependencies[:]
            for i in kept:
                tracker.formula_owner_dependencies.add().identifier = i
            entries = [e for e in tracker.owner_id_map.map_entry if e.internal_owner_id not in removed_owners]
            del tracker.owner_id_map.map_entry[:]
            for e in entries:
                tracker.owner_id_map.map_entry.add().CopyFrom(e)
            for i in gone:
                package.remove_object_reference(engine_id, i)
            package.mark_changed(engine_id)
    if OBJECT_CONTAINER_FILE in package._iwa:
        container_id = package.component_for_file(OBJECT_CONTAINER_FILE).identifier
        container = package.get(container_id)
        kept = [r.identifier for r in container.objects if r.identifier not in gone]
        if len(kept) != len(container.objects):
            del container.objects[:]
            for i in kept:
                container.objects.add().identifier = i
            package.mark_changed(container_id)

    components = {c.identifier for c in package.metadata.components}
    for i in ids:
        if i not in package:
            continue
        name = package.file_of(i)
        if i in components:
            package.remove_file(name)
            package.remove_component(i)
        else:
            package.remove_segment(i)
            component = package.component_for_file(name)
            entries = [e for e in component.object_uuid_map_entries if e.identifier != i]
            if len(entries) != len(component.object_uuid_map_entries):
                del component.object_uuid_map_entries[:]
                for e in entries:
                    component.object_uuid_map_entries.add().CopyFrom(e)
    for c in package.metadata.components:
        refs = [e for e in c.external_references if not (e.HasField("object_identifier") and e.object_identifier in gone)]
        if len(refs) != len(c.external_references):
            del c.external_references[:]
            for e in refs:
                c.external_references.add().CopyFrom(e)
    package.mark_changed(METADATA_ID)
