/**
 * Structural edits to the slide list: reorder, delete and duplicate slides.
 *
 * Slides hang off ``KN.ShowArchive.slideTree.slides`` as references to
 * ``KN.SlideNodeArchive`` objects, which live in ``Index/Document.iwa``. Each
 * node points at a ``KN.SlideArchive``, stored with everything drawn on that
 * slide in its own component file, ``Index/Slide-<id>.iwa``.
 */

import { parseIwa, serializeIwa, RawArchive, type Segment } from "./iwa.js";
import {
  METADATA_ID,
  newUuidParts,
  referencesIn,
  remapReferences,
  uuidKey,
  type Package,
  type UuidParts,
} from "./package.js";
import { clear, clone, create, has, typeOf, walk, type Message } from "./protobuf.js";

function treeIds(show: Message): number[] {
  return (show.slideTree.slides as Message[]).map((ref) => ref.identifier);
}

export function setTree(pkg: Package, showId: number, nodeIds: number[]): void {
  const show = pkg.get(showId);
  show.slideTree.slides = nodeIds.map((identifier) => create("TSP.Reference", { identifier }));
  pkg.markChanged(showId);
}

export function deleteSlide(pkg: Package, showId: number, index: number): void {
  const ids = treeIds(pkg.get(showId));
  if (ids.length === 1) throw new Error("a presentation needs at least one slide");
  const [nodeId] = ids.splice(index, 1);
  const slideId: number = pkg.get(nodeId).slide.identifier;
  setTree(pkg, showId, ids);
  pkg.removeObjectReference(showId, nodeId);

  // Anything else pointing at the node, such as the saved selection in
  // ViewState.iwa, moves to a slide that still exists.
  const replacement = ids[Math.min(index, ids.length - 1)];
  for (const [identifier, obj] of [...pkg.objects()]) {
    if (identifier === nodeId || identifier === showId) continue;
    if (referencesIn(obj).includes(nodeId)) {
      remapReferences(obj, new Map([[nodeId, replacement]]));
      const refs: number[] = pkg.segment(identifier).header.message_infos[0].object_references;
      if (refs.includes(nodeId)) {
        pkg.removeObjectReference(identifier, nodeId);
        pkg.addObjectReference(identifier, replacement);
      }
      pkg.markChanged(identifier);
    }
  }

  const documentFile = pkg.fileOf(nodeId);
  pkg.removeSegment(nodeId);
  forgetObjects(pkg.componentForFile(documentFile), new Set([nodeId]));

  const slideFile = pkg.fileOf(slideId);
  const component = pkg.componentForFile(slideFile);
  pkg.removeFile(slideFile);
  pkg.removeComponent(component.identifier);
}

/** Drop a component's UUID and data-usage entries for objects that no longer exist. */
function forgetObjects(component: Message, ids: Set<number>): void {
  component.object_uuid_map_entries = (component.object_uuid_map_entries as Message[]).filter((e) => !ids.has(e.identifier));
  for (const ref of component.data_references as Message[]) {
    ref.object_reference_list = (ref.object_reference_list as Message[]).filter((o) => !ids.has(o.object_identifier));
  }
  component.data_references = (component.data_references as Message[]).filter((r) => r.object_reference_list.length > 0);
}

/** Copy the slide at ``index`` and insert the copy at ``to``. Returns the new node's identifier. */
export function duplicateSlide(pkg: Package, showId: number, index: number, to: number): number {
  const ids = treeIds(pkg.get(showId));
  const srcNodeId = ids[index];
  const srcNode = pkg.get(srcNodeId);
  const srcSlideId: number = srcNode.slide.identifier;
  const srcFile = pkg.fileOf(srcSlideId);
  const srcComponent = pkg.componentForFile(srcFile);

  // New identifiers for everything in the slide's file.
  const idMap = new Map<number, number>();
  for (const i of pkg.idsInFile(srcFile)) idMap.set(i, pkg.newIdentifier());
  const newSlideId = idMap.get(srcSlideId)!;
  const uuidMap = new Map<string, UuidParts>();
  for (const entry of srcComponent.object_uuid_map_entries as Message[]) {
    uuidMap.set(uuidKey(entry.uuid.lower, entry.uuid.upper), newUuidParts());
  }

  const copy: Segment[] = parseIwa(serializeIwa(pkg.segmentsOf(srcFile)));
  for (const segment of copy) {
    segment.header.identifier = idMap.get(segment.header.identifier) ?? segment.header.identifier;
    for (const info of segment.header.message_infos as Message[]) {
      info.object_references = (info.object_references as number[]).map((r) => idMap.get(r) ?? r);
    }
    for (const obj of segment.objects) {
      if (obj instanceof RawArchive) continue;
      remapReferences(obj, idMap);
      remapKnownUuids(obj, uuidMap);
    }
  }
  const newFile = `Index/Slide-${newSlideId}.iwa`;
  pkg.addFile(newFile, copy);

  const meta = pkg.metadata;
  const component = clone(srcComponent);
  component.identifier = newSlideId;
  component.locator = `Slide-${newSlideId}`;
  component.preferred_locator = "Slide";
  for (const entry of component.object_uuid_map_entries as Message[]) {
    entry.identifier = idMap.get(entry.identifier) ?? entry.identifier;
    [entry.uuid.lower, entry.uuid.upper] = uuidMap.get(uuidKey(entry.uuid.lower, entry.uuid.upper))!;
  }
  for (const ref of component.data_references as Message[]) {
    for (const o of ref.object_reference_list as Message[]) {
      o.object_identifier = idMap.get(o.object_identifier) ?? o.object_identifier;
    }
  }
  // Components that refer to the source slide now refer to the copy too.
  for (const other of meta.components as Message[]) {
    for (const e of [...(other.external_references as Message[])]) {
      if (e.component_identifier === srcComponent.identifier) {
        const added = clone(e);
        added.component_identifier = newSlideId;
        if (has(e, "object_identifier") && idMap.has(e.object_identifier)) {
          added.object_identifier = idMap.get(e.object_identifier);
        }
        other.external_references.push(added);
      }
    }
  }
  meta.components.push(component);

  // A new slide node in the document, pointing at the copy.
  const newNodeId = pkg.newIdentifier();
  const nodeSegment = pkg.segment(srcNodeId);
  const node = clone(srcNode);
  node.slide.identifier = newSlideId;
  clear(node, "thumbnails");
  clear(node, "thumbnailSizes");
  node.thumbnailsAreDirty = true;
  const header = clone(nodeSegment.header);
  header.identifier = newNodeId;
  for (const info of header.message_infos as Message[]) {
    info.object_references = (info.object_references as number[]).map((r) => (r === srcSlideId ? newSlideId : r));
    clear(info, "data_references");
  }
  const documentFile = pkg.fileOf(srcNodeId);
  pkg.addSegment(documentFile, { header, objects: [node] });
  const document = pkg.componentForFile(documentFile);
  for (const entry of [...(document.object_uuid_map_entries as Message[])]) {
    if (entry.identifier === srcNodeId) {
      const [lower, upper] = newUuidParts();
      document.object_uuid_map_entries.push(
        create("TSP.ObjectUUIDMapEntry", {
          identifier: newNodeId,
          uuid: create("TSP.UUID", { lower, upper }),
        }),
      );
    }
  }
  pkg.markChanged(METADATA_ID);

  ids.splice(to, 0, newNodeId);
  setTree(pkg, showId, ids);
  pkg.addObjectReference(showId, newNodeId);
  return newNodeId;
}

function remapKnownUuids(message: Message, uuidMap: Map<string, UuidParts>): void {
  walk(message, (m) => {
    if (typeOf(m) !== "TSP.UUID") return;
    const parts = uuidMap.get(uuidKey(m.lower, m.upper));
    if (parts) [m.lower, m.upper] = parts;
  });
}
