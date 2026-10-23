"""Structural edits to the slide list: reorder, delete and duplicate slides.

Slides hang off ``KN.ShowArchive.slideTree.slides`` as references to
``KN.SlideNodeArchive`` objects, which live in ``Index/Document.iwa``. Each
node points at a ``KN.SlideArchive``, stored with everything drawn on that
slide in its own component file, ``Index/Slide-<id>.iwa``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from keynote_parser.codec import IWAArchiveSegment, IWAFile

from .package import (
    METADATA_ID,
    Package,
    new_uuid_parts,
    references_in,
    remap_references,
    walk_messages,
)


def _tree_ids(show: Any) -> List[int]:
    return [ref.identifier for ref in show.slideTree.slides]


def set_tree(package: Package, show_id: int, node_ids: List[int]) -> None:
    show = package.get(show_id)
    del show.slideTree.slides[:]
    for node_id in node_ids:
        show.slideTree.slides.add().identifier = node_id
    package.mark_changed(show_id)


def move_slide(package: Package, show_id: int, old: int, new: int) -> None:
    ids = _tree_ids(package.get(show_id))
    ids.insert(new, ids.pop(old))
    set_tree(package, show_id, ids)


def delete_slide(package: Package, show_id: int, index: int) -> None:
    show = package.get(show_id)
    ids = _tree_ids(show)
    if len(ids) == 1:
        raise ValueError("a presentation needs at least one slide")
    node_id = ids.pop(index)
    slide_id = package.get(node_id).slide.identifier
    set_tree(package, show_id, ids)
    package.remove_object_reference(show_id, node_id)

    # Anything else pointing at the node, such as the saved selection in
    # ViewState.iwa, moves to a slide that still exists.
    replacement = ids[min(index, len(ids) - 1)]
    for identifier, obj in list(package.objects()):
        if identifier in (node_id, show_id):
            continue
        if node_id in references_in(obj):
            remap_references(obj, {node_id: replacement})
            refs = package.segment(identifier).header.message_infos[0].object_references
            if node_id in refs:
                package.remove_object_reference(identifier, node_id)
                package.add_object_reference(identifier, replacement)
            package.mark_changed(identifier)

    document_file = package.file_of(node_id)
    package.remove_segment(node_id)
    document = package.component_for_file(document_file)
    _forget_objects(document, {node_id})

    slide_file = package.file_of(slide_id)
    component = package.component_for_file(slide_file)
    package.remove_file(slide_file)
    package.remove_component(component.identifier)


def _forget_objects(component: Any, ids: set) -> None:
    """Drop a component's UUID and data-usage entries for objects that no longer exist."""
    entries = [e for e in component.object_uuid_map_entries if e.identifier not in ids]
    del component.object_uuid_map_entries[:]
    for e in entries:
        component.object_uuid_map_entries.add().CopyFrom(e)
    for ref in list(component.data_references):
        kept = [o for o in ref.object_reference_list if o.object_identifier not in ids]
        del ref.object_reference_list[:]
        for o in kept:
            ref.object_reference_list.add().CopyFrom(o)
    kept_refs = [r for r in component.data_references if len(r.object_reference_list) > 0]
    del component.data_references[:]
    for r in kept_refs:
        component.data_references.add().CopyFrom(r)


def duplicate_slide(package: Package, show_id: int, index: int, to: int) -> int:
    """Copy the slide at ``index`` and insert the copy at ``to``. Returns the new node's identifier."""
    ids = _tree_ids(package.get(show_id))
    src_node_id = ids[index]
    src_node = package.get(src_node_id)
    src_slide_id = src_node.slide.identifier
    src_file = package.file_of(src_slide_id)
    src_component = package.component_for_file(src_file)

    # New identifiers for everything in the slide's file.
    id_map: Dict[int, int] = {i: package.new_identifier() for i in package.ids_in_file(src_file)}
    new_slide_id = id_map[src_slide_id]
    uuid_map: Dict[Tuple[int, int], Tuple[int, int]] = {}
    for entry in src_component.object_uuid_map_entries:
        uuid_map[(entry.uuid.lower, entry.uuid.upper)] = new_uuid_parts()

    copy = IWAFile.from_buffer(package._iwa[src_file].to_buffer())
    for chunk in copy.chunks:
        for segment in chunk.archives:
            segment.header.identifier = id_map[segment.header.identifier]
            for info in segment.header.message_infos:
                refs = [id_map.get(r, r) for r in info.object_references]
                del info.object_references[:]
                info.object_references.extend(refs)
            for obj in segment.objects:
                if hasattr(obj, "ListFields"):
                    remap_references(obj, id_map)
                    _remap_known_uuids(obj, uuid_map)
    new_file = f"Index/Slide-{new_slide_id}.iwa"
    package.add_file(new_file, copy)

    meta = package.metadata
    component = meta.components.add()
    component.CopyFrom(src_component)
    component.identifier = new_slide_id
    component.locator = f"Slide-{new_slide_id}"
    component.preferred_locator = "Slide"
    for entry in component.object_uuid_map_entries:
        entry.identifier = id_map.get(entry.identifier, entry.identifier)
        entry.uuid.lower, entry.uuid.upper = uuid_map[(entry.uuid.lower, entry.uuid.upper)]
    for ref in component.data_references:
        for o in ref.object_reference_list:
            o.object_identifier = id_map.get(o.object_identifier, o.object_identifier)
    # Components that refer to the source slide now refer to the copy too.
    for other in list(meta.components):
        for e in list(other.external_references):
            if e.component_identifier == src_component.identifier and other.identifier != new_slide_id:
                added = other.external_references.add()
                added.CopyFrom(e)
                added.component_identifier = new_slide_id
                if e.HasField("object_identifier") and e.object_identifier in id_map:
                    added.object_identifier = id_map[e.object_identifier]

    # A new slide node in the document, pointing at the copy.
    new_node_id = package.new_identifier()
    node_segment = package.segment(src_node_id)
    node = type(src_node)()
    node.CopyFrom(src_node)
    node.slide.identifier = new_slide_id
    node.ClearField("thumbnails")
    node.ClearField("thumbnailSizes")
    node.thumbnailsAreDirty = True
    header = type(node_segment.header)()
    header.CopyFrom(node_segment.header)
    header.identifier = new_node_id
    for info in header.message_infos:
        refs = [new_slide_id if r == src_slide_id else r for r in info.object_references]
        del info.object_references[:]
        info.object_references.extend(refs)
        del info.data_references[:]
    document_file = package.file_of(src_node_id)
    package.add_segment(document_file, IWAArchiveSegment(header, [node]))
    document = package.component_for_file(document_file)
    for entry in list(document.object_uuid_map_entries):
        if entry.identifier == src_node_id:
            added = document.object_uuid_map_entries.add()
            added.identifier = new_node_id
            added.uuid.lower, added.uuid.upper = new_uuid_parts()
    package.mark_changed(METADATA_ID)

    ids.insert(to, new_node_id)
    set_tree(package, show_id, ids)
    package.add_object_reference(show_id, new_node_id)
    return new_node_id


def _remap_known_uuids(message: Any, uuid_map: Dict[Tuple[int, int], Tuple[int, int]]) -> None:
    def visit(m: Any) -> None:
        if m.DESCRIPTOR.full_name == "TSP.UUID":
            key = (m.lower, m.upper)
            if key in uuid_map:
                m.lower, m.upper = uuid_map[key]

    walk_messages(message, visit)
