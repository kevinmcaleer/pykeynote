/**
 * Copy a drawable, with everything it owns, from one .key package into a slide of another.
 *
 * Charts and tables are too intricate to write from nothing, so new ones are
 * copied from a small deck that Keynote made (``templates/parts/``) and then
 * given their own data. A drawable's objects can live in several places: the
 * slide's own component file, ``Index/ObjectContainer.iwa`` (chart settings),
 * ``Index/CalculationEngine.iwa`` (table models) and components of their own
 * (a table's cell tiles and string lists). Each copied object gets a new
 * identifier in the same kind of place in the target package.
 *
 * Styles are not copied. The drawable keeps using the target theme's styles
 * of the same name (every theme names its styles, e.g. ``chart-0-series_2``),
 * and its theme preset becomes the target theme's preset at the same
 * position. UUIDs inside the copied objects are replaced consistently, so a
 * copy never shares an identity with its source or with another copy.
 */

import { STYLESHEET_FILE, addExternalReference, namedStyles, stylesheetId } from "./drawables.js";
import { RawArchive, type Segment } from "./iwa.js";
import {
  METADATA_ID,
  addUuid,
  headerRefs,
  int64,
  newUuidParts,
  referencesIn,
  remapReferences,
  type Package,
} from "./package.js";
import { clear, clone, create, fieldsOf, has, typeOf, walk, type Message } from "./protobuf.js";

export const OBJECT_CONTAINER_FILE = "Index/ObjectContainer.iwa";
export const CALC_ENGINE_FILE = "Index/CalculationEngine.iwa";
export const DOCUMENT_FILE = "Index/Document.iwa";

const SHARED_FILES = [OBJECT_CONTAINER_FILE, CALC_ENGINE_FILE];
const PRESET_LISTS = ["chart_presets", "table_style_presets"];
const UUID_STRING = /^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$/;
const STRING = 9;
const MASK_64 = (1n << 64n) - 1n;

/** The type of the archive with this identifier, or ``undefined`` if keynotejs can't read it. */
export function typeAt(pkg: Package, identifier: number): string | undefined {
  try {
    return typeOf(pkg.get(identifier));
  } catch {
    return undefined;
  }
}

/** Identifiers of the theme's chart and table presets, by list name. */
export function themePresets(pkg: Package): Record<string, number[]> {
  const show = pkg.get(pkg.get(1).show.identifier);
  const theme = pkg.deref(show.theme).super;
  const out: Record<string, number[]> = {};
  for (const f of fieldsOf(typeOf(theme))) {
    // Extensions are named by their full name, e.g. "TSCH.ChartPresetsArchive.extension".
    if (!f.name.includes(".") || f.messageType === null || !has(theme, f.name)) continue;
    const value = theme[f.name];
    for (const name of PRESET_LISTS) {
      if (fieldsOf(f.messageType).some((g) => g.name === name)) out[name] = (value[name] as Message[]).map((r) => r.identifier);
    }
  }
  return out;
}

function presetMap(src: Package, dst: Package): Map<number, number> {
  const s = themePresets(src);
  const d = themePresets(dst);
  const out = new Map<number, number>();
  for (const [name, ids] of Object.entries(s)) {
    const targets = d[name] ?? [];
    ids.forEach((identifier, i) => {
      if (i < targets.length) out.set(identifier, targets[i]);
    });
  }
  return out;
}

/**
 * New values for the UUIDs in copied objects, the same new value each time an old one is met.
 *
 * Keynote numbers related formula owners as one base UUID plus a small
 * offset, so UUIDs within ``familySpan`` of one already mapped keep that
 * offset from its new value.
 */
export class UUIDMap {
  readonly map = new Map<bigint, bigint>();

  constructor(private readonly span = 4096n) {}

  get(value: bigint): bigint {
    const found = this.map.get(value);
    if (found !== undefined) return found;
    if (value < 1n << 16n) return value; // well-known owners such as 666, not real UUIDs
    for (const [old, mapped] of this.map) {
      const delta = value - old;
      if (old >> 64n === value >> 64n && (delta < 0n ? -delta : delta) < this.span) {
        this.map.set(value, mapped + delta);
        return mapped + delta;
      }
    }
    const [lower, upper] = newUuidParts().map((v) => BigInt(v));
    const fresh = (upper << 64n) | (lower & ~0xffffn) | 0x8000n;
    this.map.set(value, fresh);
    return fresh;
  }
}

function uuidStringValue(text: string): bigint {
  const hex = text.replaceAll("-", "");
  let value = 0n;
  // The string's bytes, read little-endian: the same number as its CFUUID form.
  for (let i = 15; i >= 0; i--) value = (value << 8n) | BigInt(parseInt(hex.slice(i * 2, i * 2 + 2), 16));
  return value;
}

function uuidString(value: bigint): string {
  let hex = "";
  for (let i = 0; i < 16; i++) hex += Number((value >> BigInt(8 * i)) & 0xffn).toString(16).padStart(2, "0");
  hex = hex.toUpperCase();
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function remapUuids(message: Message, uuids: UUIDMap, strings: Map<string, string>): void {
  walk(message, (m) => {
    const name = typeOf(m);
    if (name === "TSP.UUID") {
      if (has(m, "lower") || has(m, "upper")) {
        const fresh = uuids.get((BigInt(m.upper) << 64n) | BigInt(m.lower));
        m.lower = int64(fresh & MASK_64);
        m.upper = int64(fresh >> 64n);
      }
    } else if (name === "TSP.CFUUIDArchive") {
      const fields = ["uuid_w0", "uuid_w1", "uuid_w2", "uuid_w3"];
      if (fields.some((f) => has(m, f))) {
        let value = 0n;
        fields.forEach((f, i) => (value |= BigInt(m[f]) << BigInt(32 * i)));
        const fresh = uuids.get(value);
        fields.forEach((f, i) => (m[f] = Number((fresh >> BigInt(32 * i)) & 0xffffffffn)));
      }
    }
    for (const f of fieldsOf(name)) {
      if (f.type !== STRING || f.repeated || !has(m, f.name) || !UUID_STRING.test(m[f.name])) continue;
      // A UUID written out, such as a table's table_id. Its bytes are the same UUID as
      // the CFUUID form (w0 first, little-endian), so it maps the same way.
      const value: string = m[f.name];
      if (!strings.has(value)) strings.set(value, uuidString(uuids.get(uuidStringValue(value))));
      m[f.name] = strings.get(value);
    }
  });
}

/** Copies drawables from ``src`` into ``dst``. One importer can copy several drawables. */
export class Importer {
  /** Source objects that stand for an existing target object. */
  readonly fixed = new Map<number, number>();
  private readonly srcStyleIds: Set<number>;

  /**
   * ``rename`` maps a source style name to the target style to use instead, and
   * ``presets`` a source preset to a target preset; by default both keep their name or position.
   */
  constructor(
    readonly src: Package,
    readonly dst: Package,
    rename?: (name: string) => string,
    presets?: Map<number, number>,
  ) {
    const dstStyles = namedStyles(dst);
    for (const [name, identifier] of namedStyles(src)) {
      const target = rename ? rename(name) : name;
      const found = dstStyles.get(target);
      if (found !== undefined) this.fixed.set(identifier, found);
    }
    this.fixed.set(stylesheetId(src), stylesheetId(dst));
    for (const [k, v] of presetMap(src, dst)) this.fixed.set(k, v);
    for (const [k, v] of presets ?? []) this.fixed.set(k, v);
    this.srcStyleIds = new Set(src.idsInFile(STYLESHEET_FILE));
  }

  /** Every object ``root`` owns: what it refers to, short of styles, presets and ``stop``. */
  closure(root: number, stop: Set<number>): number[] {
    const seen: number[] = [];
    const found = new Set<number>();
    const todo = [root];
    while (todo.length) {
      const i = todo.shift()!;
      if (found.has(i) || stop.has(i) || this.fixed.has(i)) continue;
      if (this.srcStyleIds.has(i)) {
        throw new Error(`can't copy: the target theme has no style matching ${typeAt(this.src, i)} ${i}`);
      }
      if (this.src.fileOf(i) === DOCUMENT_FILE) throw new Error(`can't copy: the drawable refers to document object ${i}`);
      found.add(i);
      seen.push(i);
      todo.push(...headerRefs(this.src, i));
    }
    return seen;
  }

  /**
   * Copy ``root`` (and ``extra`` objects it needs but doesn't refer to) onto the target slide.
   *
   * Returns the map from source to new identifiers. The caller puts the new
   * root on the slide.
   */
  copyDrawable(root: number, srcSlideId: number, dstSlideId: number, extra: number[] = []): Map<number, number> {
    const { src, dst } = this;
    const srcSlideFile = src.fileOf(srcSlideId);
    const dstSlideFile = dst.fileOf(dstSlideId);
    const ids = this.closure(root, new Set([srcSlideId]));
    for (const i of extra) {
      for (const j of this.closure(i, new Set([srcSlideId, ...ids]))) ids.push(j);
    }

    const idMap = new Map(ids.map((i) => [i, dst.newIdentifier()]));
    const refMap = new Map(this.fixed);
    refMap.set(srcSlideId, dstSlideId);
    for (const [k, v] of idMap) refMap.set(k, v);

    const uuids = new UUIDMap();
    const strings = new Map<string, string>();
    const newComponents = new Map<string, string>(); // source file -> target file

    const placed: [string, number][] = [];
    for (const i of ids) {
      const srcFile = src.fileOf(i);
      let dstFile: string;
      if (srcFile === srcSlideFile) {
        dstFile = dstSlideFile;
      } else if (SHARED_FILES.includes(srcFile)) {
        dstFile = srcFile;
        this.ensureSharedFile(dstFile);
      } else {
        dstFile = this.newComponentFile(srcFile, i, idMap, newComponents);
      }
      const segment = src.segment(i);
      const header = clone(segment.header);
      header.identifier = idMap.get(i);
      for (const info of header.message_infos as Message[]) {
        info.object_references = (info.object_references as number[]).map((r) => refMap.get(r) ?? r);
        info.data_references = [];
      }
      const objects = segment.objects.map((obj) => {
        if (obj instanceof RawArchive) return obj;
        const copy = clone(obj);
        remapReferences(copy, refMap);
        remapUuids(copy, uuids, strings);
        return copy;
      });
      dst.addSegment(dstFile, { header, objects } as Segment);
      placed.push([dstFile, idMap.get(i)!]);
      if (dstFile === OBJECT_CONTAINER_FILE) {
        const containerId = this.containerId();
        dst.get(containerId).objects.push(create("TSP.Reference", { identifier: idMap.get(i) }));
        dst.markChanged(containerId);
      }
    }

    // Component bookkeeping: UUIDs for objects Keynote tracks, and references between components.
    for (const i of ids) {
      const srcComponent = src.componentForFile(src.fileOf(i));
      const dstComponent = dst.componentForFile(dst.fileOf(idMap.get(i)!));
      for (const e of srcComponent.object_uuid_map_entries as Message[]) {
        if (e.identifier === i) addUuid(dstComponent, idMap.get(i)!);
      }
    }
    for (const [dstFile, identifier] of placed) {
      const component = dst.componentForFile(dstFile);
      const strong = new Set(headerRefs(dst, identifier));
      for (const target of strong) if (dst.has(target)) addExternalReference(dst, component, target);
      const obj = dst.segment(identifier).objects[0];
      if (obj instanceof RawArchive) continue;
      for (const target of new Set(referencesIn(obj))) {
        if (!strong.has(target) && dst.has(target) && target !== identifier) addExternalReference(dst, component, target, true);
      }
    }
    dst.markChanged(METADATA_ID);
    return idMap;
  }

  // --- target files ---------------------------------------------------------

  private containerId(): number {
    return this.dst.componentForFile(OBJECT_CONTAINER_FILE).identifier;
  }

  private ensureSharedFile(name: string): void {
    const dst = this.dst;
    if (dst.hasArchiveFile(name)) return;
    if (name !== OBJECT_CONTAINER_FILE) throw new Error(`the target deck has no ${name}`);
    // Make an empty object container like the source's.
    const srcComponent = this.src.componentForFile(name);
    const identifier = dst.newIdentifier();
    const containerId: number = srcComponent.identifier;
    const header = clone(this.src.segment(containerId).header);
    header.identifier = identifier;
    const container = create(typeOf(this.src.get(containerId)), { identifier: 1 });
    dst.addFile(name, []);
    dst.addSegment(name, { header, objects: [container] });
    const component = clone(srcComponent);
    component.identifier = identifier;
    for (const field of ["external_references", "object_uuid_map_entries", "data_references"]) clear(component, field);
    dst.metadata.components.push(component);
    dst.markChanged(METADATA_ID);
  }

  private newComponentFile(srcFile: string, identifier: number, idMap: Map<number, number>, made: Map<string, string>): string {
    const existing = made.get(srcFile);
    if (existing !== undefined) return existing;
    const srcComponent = this.src.componentForFile(srcFile);
    if (srcComponent.identifier !== identifier) {
      throw new Error(`can't copy object ${identifier}: it shares ${srcFile} with objects that aren't being copied`);
    }
    const newId = idMap.get(identifier)!;
    const locator = `${srcComponent.preferred_locator}-${newId}`;
    const name = `Index/${locator}.iwa`;
    const component = clone(srcComponent);
    component.identifier = newId;
    component.locator = locator;
    for (const field of ["external_references", "object_uuid_map_entries", "data_references"]) clear(component, field);
    this.dst.metadata.components.push(component);
    this.dst.addFile(name, []);
    this.dst.markChanged(METADATA_ID);
    made.set(srcFile, name);
    return name;
  }
}

/** ``root`` and every object it owns, short of styles, document objects and ``stop``. */
export function ownedObjects(pkg: Package, root: number, stop: Set<number>): number[] {
  const styles = new Set(pkg.idsInFile(STYLESHEET_FILE));
  const out: number[] = [];
  const found = new Set<number>();
  const todo = [root];
  while (todo.length) {
    const i = todo.shift()!;
    if (found.has(i) || stop.has(i) || styles.has(i) || !pkg.has(i)) continue;
    if (pkg.fileOf(i) === DOCUMENT_FILE) continue;
    found.add(i);
    out.push(i);
    todo.push(...headerRefs(pkg, i));
  }
  return out;
}

/** Delete objects, with their files if they had components of their own, and every record of them. */
export function removeObjects(pkg: Package, ids: number[]): void {
  const gone = new Set(ids);
  if (pkg.hasArchiveFile(CALC_ENGINE_FILE)) {
    const engineId: number = pkg.componentForFile(CALC_ENGINE_FILE).identifier;
    const tracker = pkg.get(engineId).dependency_tracker;
    const removedOwners = new Set(
      ids.filter((i) => pkg.has(i) && typeAt(pkg, i) === "TSCE.FormulaOwnerDependenciesArchive").map((i) => pkg.get(i).internal_formula_owner_id),
    );
    if (removedOwners.size) {
      tracker.formula_owner_dependencies = (tracker.formula_owner_dependencies as Message[]).filter((r) => !gone.has(r.identifier));
      const idMap = tracker.owner_id_map;
      if (idMap) idMap.map_entry = (idMap.map_entry as Message[]).filter((e) => !removedOwners.has(e.internal_owner_id));
      for (const i of gone) pkg.removeObjectReference(engineId, i);
      pkg.markChanged(engineId);
    }
  }
  if (pkg.hasArchiveFile(OBJECT_CONTAINER_FILE)) {
    const containerId: number = pkg.componentForFile(OBJECT_CONTAINER_FILE).identifier;
    const container = pkg.get(containerId);
    const kept = (container.objects as Message[]).filter((r) => !gone.has(r.identifier));
    if (kept.length !== container.objects.length) {
      container.objects = kept;
      pkg.markChanged(containerId);
    }
  }

  const components = new Set((pkg.metadata.components as Message[]).map((c) => c.identifier as number));
  for (const i of ids) {
    if (!pkg.has(i)) continue;
    const name = pkg.fileOf(i);
    if (components.has(i)) {
      pkg.removeFile(name);
      pkg.removeComponent(i);
    } else {
      pkg.removeSegment(i);
      const component = pkg.componentForFile(name);
      const entries = (component.object_uuid_map_entries as Message[]).filter((e) => e.identifier !== i);
      if (entries.length !== component.object_uuid_map_entries.length) component.object_uuid_map_entries = entries;
    }
  }
  for (const c of pkg.metadata.components as Message[]) {
    const refs = (c.external_references as Message[]).filter((e) => !(has(e, "object_identifier") && gone.has(e.object_identifier)));
    if (refs.length !== c.external_references.length) c.external_references = refs;
  }
  pkg.markChanged(METADATA_ID);
}
