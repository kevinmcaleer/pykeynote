/**
 * The raw contents of a .key file: its archives (protobuf objects) and data files.
 *
 * A .key file is a zip (or, for older files, a folder) holding ``Index/*.iwa``
 * files and a ``Data/`` folder of images and media. Each .iwa file is a stream
 * of Snappy-compressed chunks of protobuf "archives", each with a numeric
 * identifier that other archives use to refer to it. This module indexes the
 * objects by identifier and writes back only the files that changed.
 *
 * Each .iwa file is a "component", listed in the ``TSP.PackageMetadata`` archive
 * in ``Index/Metadata.iwa``. A component records which other components it
 * refers to and the UUID of each of its objects. Each archive's header lists
 * the identifiers its object refers to. Structural edits, such as adding or
 * removing slides, have to keep all of these in step.
 */

import { unzipSync, zipSync, type Zippable } from "fflate";

import { parseIwa, serializeIwa, RawArchive, type Segment } from "./iwa.js";
import { typeOf, walk, type Message } from "./protobuf.js";

export const METADATA_ID = 2;

export class Package {
  private raw: Map<string, Uint8Array>;
  private iwa = new Map<string, Segment[]>();
  private segments = new Map<number, [string, Segment]>();
  private dirty = new Set<string>();

  constructor(files: Map<string, Uint8Array>) {
    this.raw = files;
    for (const [name, data] of files) {
      if (name.endsWith(".iwa")) this.indexFile(name, parseIwa(data, name));
    }
  }

  /** Read a .key file's bytes (a zip). */
  static fromBytes(bytes: Uint8Array): Package {
    const files = new Map<string, Uint8Array>();
    for (const [name, data] of Object.entries(unzipSync(bytes))) {
      if (!name.endsWith("/")) files.set(name, data);
    }
    return new Package(files);
  }

  private indexFile(name: string, segments: Segment[]): void {
    this.iwa.set(name, segments);
    for (const segment of segments) {
      if (segment.objects.length) this.segments.set(segment.header.identifier, [name, segment]);
    }
  }

  // --- objects --------------------------------------------------------------

  has(identifier: number): boolean {
    return this.segments.has(identifier);
  }

  /** The archive with this identifier. */
  get(identifier: number): Message {
    const entry = this.segments.get(identifier);
    if (!entry) throw new Error(`no object with identifier ${identifier}`);
    const obj = entry[1].objects[0];
    if (obj instanceof RawArchive) throw new Error(`object ${identifier} has a type keynotejs can't read (${obj.typeId})`);
    return obj;
  }

  /** Follow a ``TSP.Reference`` (anything with an ``identifier``) to its archive. */
  deref(ref: Message | { identifier: number }): Message {
    return this.get(ref.identifier);
  }

  fileOf(identifier: number): string {
    const entry = this.segments.get(identifier);
    if (!entry) throw new Error(`no object with identifier ${identifier}`);
    return entry[0];
  }

  segment(identifier: number): Segment {
    const entry = this.segments.get(identifier);
    if (!entry) throw new Error(`no object with identifier ${identifier}`);
    return entry[1];
  }

  /** ``[identifier, archive]`` pairs, optionally only those of one protobuf type, e.g. ``"KN.SlideArchive"``. */
  *objects(typeName?: string): Generator<[number, Message]> {
    for (const [identifier, [, segment]] of this.segments) {
      const obj = segment.objects[0];
      if (obj instanceof RawArchive) continue;
      if (typeName === undefined || typeOf(obj) === typeName) yield [identifier, obj];
    }
  }

  idsInFile(name: string): number[] {
    return (this.iwa.get(name) ?? []).filter((s) => s.objects.length).map((s) => s.header.identifier);
  }

  /** The parsed segments of an .iwa file. */
  segmentsOf(name: string): Segment[] {
    const segments = this.iwa.get(name);
    if (!segments) throw new Error(`no archive file ${name}`);
    return segments;
  }

  /** Record that an archive was edited in place, so its file is re-encoded on save. */
  markChanged(identifier: number): void {
    this.dirty.add(this.fileOf(identifier));
  }

  newIdentifier(): number {
    const meta = this.metadata;
    meta.last_object_identifier = Number(meta.last_object_identifier) + 1;
    this.markChanged(METADATA_ID);
    return meta.last_object_identifier;
  }

  private references(owner: number): number[] {
    return this.segment(owner).header.message_infos[0].object_references;
  }

  addObjectReference(owner: number, target: number): void {
    const refs = this.references(owner);
    if (!refs.includes(target)) {
      refs.push(target);
      this.markChanged(owner);
    }
  }

  removeObjectReference(owner: number, target: number): void {
    const info = this.segment(owner).header.message_infos[0];
    const refs: number[] = info.object_references;
    if (refs.includes(target)) {
      info.object_references = refs.filter((r) => r !== target);
      this.markChanged(owner);
    }
  }

  /** Append an archive segment to an existing .iwa file. */
  addSegment(name: string, segment: Segment): void {
    this.segmentsOf(name).push(segment);
    this.segments.set(segment.header.identifier, [name, segment]);
    this.dirty.add(name);
  }

  removeSegment(identifier: number): void {
    const [name, segment] = this.segments.get(identifier)!;
    this.segments.delete(identifier);
    this.iwa.set(
      name,
      this.segmentsOf(name).filter((s) => s !== segment),
    );
    this.dirty.add(name);
  }

  // --- components -----------------------------------------------------------

  /** The ``TSP.PackageMetadata`` archive. */
  get metadata(): Message {
    return this.get(METADATA_ID);
  }

  component(identifier: number): Message {
    const found = (this.metadata.components as Message[]).find((c) => c.identifier === identifier);
    if (!found) throw new Error(`no component ${identifier}`);
    return found;
  }

  componentForFile(name: string): Message {
    const locator = name.slice("Index/".length, -".iwa".length);
    const found = (this.metadata.components as Message[]).find(
      (c) => c.locator === locator || (!c.locator && c.preferred_locator === locator),
    );
    if (!found) throw new Error(`no component for ${name}`);
    return found;
  }

  addFile(name: string, segments: Segment[]): void {
    this.raw.set(name, new Uint8Array(0));
    this.indexFile(name, segments);
    this.dirty.add(name);
  }

  removeFile(name: string): void {
    for (const identifier of this.idsInFile(name)) this.segments.delete(identifier);
    this.iwa.delete(name);
    this.raw.delete(name);
    this.dirty.delete(name);
  }

  /** Remove a component's entry and every other component's references to it. */
  removeComponent(identifier: number): void {
    const meta = this.metadata;
    meta.components = (meta.components as Message[]).filter((c) => c.identifier !== identifier);
    for (const c of meta.components as Message[]) {
      if (c.external_references.length) {
        c.external_references = (c.external_references as Message[]).filter((e) => e.component_identifier !== identifier);
      }
    }
    this.markChanged(METADATA_ID);
  }

  // --- data files -----------------------------------------------------------

  get filenames(): string[] {
    return [...this.raw.keys()].sort();
  }

  readFile(name: string): Uint8Array {
    const data = this.raw.get(name);
    if (!data) throw new Error(`no file ${name}`);
    return data;
  }

  // --- saving ---------------------------------------------------------------

  /** The current contents of every file, re-encoding the archives that changed. */
  files(): Map<string, Uint8Array> {
    const out = new Map<string, Uint8Array>();
    for (const name of this.filenames) {
      out.set(name, this.dirty.has(name) ? serializeIwa(this.iwa.get(name)!) : this.raw.get(name)!);
    }
    return out;
  }

  toBytes(): Uint8Array {
    const entries: Zippable = {};
    // Keynote writes .key zips uncompressed; the .iwa files are already compressed.
    for (const [name, data] of this.files()) entries[name] = [data, { level: 0 }];
    return zipSync(entries, { level: 0 });
  }
}

export function isReference(m: Message): boolean {
  return typeOf(m) === "TSP.Reference";
}

/** Point every ``TSP.Reference`` inside ``message`` at its new identifier. */
export function remapReferences(message: Message, idMap: Map<number, number>): void {
  walk(message, (m) => {
    if (isReference(m) && idMap.has(m.identifier)) m.identifier = idMap.get(m.identifier);
  });
}

export function referencesIn(message: Message): number[] {
  const found: number[] = [];
  walk(message, (m) => {
    if (isReference(m)) found.push(m.identifier);
  });
  return found;
}

export type UuidParts = [number | bigint, number | bigint];

export function uuidKey(lower: number | bigint, upper: number | bigint): string {
  return `${lower}:${upper}`;
}

export function newUuidParts(): UuidParts {
  const words = new BigUint64Array(2);
  globalThis.crypto.getRandomValues(words);
  // Mark it as a version 4 UUID, as Python's uuid4() does.
  let upper = words[1];
  let lower = words[0];
  upper = (upper & ~(0xfn << 12n)) | (4n << 12n);
  lower = (lower & ~(0x3n << 62n)) | (0x2n << 62n);
  return [lower, upper];
}
