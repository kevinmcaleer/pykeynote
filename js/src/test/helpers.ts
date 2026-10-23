import { createHash } from "node:crypto";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { deflateSync } from "node:zlib";
import assert from "node:assert/strict";

import { Presentation } from "../index.js";
import { referencesIn } from "../package.js";
import type { Message } from "../protobuf.js";

export const FIXTURES = fileURLToPath(new URL("../../../tests/fixtures/", import.meta.url));

export function fixture(name: string): Promise<Presentation> {
  return Presentation.open(join(FIXTURES, name));
}

export function tmpPath(name = "out.key"): string {
  return join(mkdtempSync(join(tmpdir(), "keynotejs-")), name);
}

export async function reopen(deck: Presentation, name = "out.key"): Promise<Presentation> {
  const out = tmpPath(name);
  await deck.save(out);
  return Presentation.open(out);
}

/** Every slide node, slide and component the show refers to exists, and nothing dangles. */
export function checkConsistent(deck: Presentation): void {
  const p = deck.package;
  const showId: number = (deck as any).showId;
  const show = p.get(showId);
  const showRefs = new Set<number>(p.segment(showId).header.message_infos[0].object_references);
  const components = new Map<number, Message>((p.metadata.components as Message[]).map((c) => [c.identifier, c]));
  for (const ref of show.slideTree.slides as Message[]) {
    assert.ok(showRefs.has(ref.identifier));
    const slideId: number = p.get(ref.identifier).slide.identifier;
    assert.ok(p.has(slideId));
    const c = components.get(slideId);
    assert.ok(c, "slide has no component");
    assert.equal(p.fileOf(slideId), `Index/${c.locator || c.preferred_locator}.iwa`);
  }
  for (const c of components.values()) {
    for (const e of c.external_references as Message[]) {
      assert.ok(components.has(e.component_identifier) || e.component_identifier === 0);
    }
  }
  const files = new Set([...components.values()].map((c) => `Index/${c.locator || c.preferred_locator}.iwa`));
  files.add("Index/Metadata.iwa");
  for (const n of p.filenames) if (n.startsWith("Index/")) assert.ok(files.has(n), `${n} has no component`);
  const ids = [...p.objects()].map(([i]) => i);
  assert.equal(new Set(ids).size, ids.length);
  assert.ok(Math.max(...ids) <= p.metadata.last_object_identifier);
}

// --- pictures ------------------------------------------------------------------

const CRC_TABLE = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});

function crc32(data: Uint8Array): number {
  let c = 0xffffffff;
  for (const b of data) c = CRC_TABLE[(c ^ b) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function u32(n: number): Uint8Array {
  const out = new Uint8Array(4);
  new DataView(out.buffer).setUint32(0, n);
  return out;
}

function concatBytes(...parts: Uint8Array[]): Uint8Array {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let at = 0;
  for (const p of parts) {
    out.set(p, at);
    at += p.length;
  }
  return out;
}

const ascii = (s: string) => new TextEncoder().encode(s);

/** A solid-colour PNG, made without any imaging library. */
export function png(width: number, height: number, rgb: [number, number, number] = [200, 30, 30]): Uint8Array {
  const row = new Uint8Array(1 + 3 * width);
  for (let x = 0; x < width; x++) row.set(rgb, 1 + 3 * x);
  const raw = new Uint8Array(row.length * height);
  for (let y = 0; y < height; y++) raw.set(row, y * row.length);
  const chunk = (kind: string, data: Uint8Array) => concatBytes(u32(data.length), ascii(kind), data, u32(crc32(concatBytes(ascii(kind), data))));
  const ihdr = concatBytes(u32(width), u32(height), Uint8Array.of(8, 2, 0, 0, 0));
  return concatBytes(Uint8Array.of(0x89), ascii("PNG\r\n\x1a\n"), chunk("IHDR", ihdr), chunk("IDAT", deflateSync(raw)), chunk("IEND", new Uint8Array(0)));
}

/** Just enough of a JPEG for its size to be read. */
export function jpegHeader(width: number, height: number): Uint8Array {
  const app0 = concatBytes(Uint8Array.of(0xff, 0xe0, 0, 16), ascii("JFIF\x00"), Uint8Array.of(1, 1, 0, 0, 1, 0, 1, 0, 0));
  const sof = Uint8Array.of(0xff, 0xc0, 0, 11, 8, height >> 8, height & 0xff, width >> 8, width & 0xff, 1, 1, 0x11, 0);
  return concatBytes(Uint8Array.of(0xff, 0xd8), app0, sof, Uint8Array.of(0xff, 0xd9));
}

/** Every TSP.Reference in the package points at an object that exists. */
export function assertNoDanglingReferences(deck: Presentation): void {
  const p = deck.package;
  const missing: [number, number][] = [];
  for (const [i, obj] of p.objects()) for (const r of referencesIn(obj)) if (!p.has(r)) missing.push([i, r]);
  assert.deepEqual(missing, []);
}

/** Every data file an image uses is in the package with the right digest and listed in its component. */
export function checkData(deck: Presentation): void {
  const p = deck.package;
  const infos = new Map((p.metadata.datas as Message[]).map((i) => [i.identifier, i]));
  for (const slide of deck) {
    const component = p.componentForFile(p.fileOf(slide.slideId));
    const used = new Set<string>();
    for (const r of component.data_references as Message[]) for (const o of r.object_reference_list as Message[]) used.add(`${o.object_identifier}:${r.data_identifier}`);
    for (const image of slide.images) {
      const obj = p.get(image.identifier);
      assert.ok(p.segment(image.identifier).header.message_infos[0].data_references.includes(obj.data.identifier));
      assert.ok(used.has(`${image.identifier}:${obj.data.identifier}`));
      if (!image.isSample) {
        const info = infos.get(obj.data.identifier)!;
        const data = p.readFile("Data/" + info.file_name);
        assert.deepEqual(new Uint8Array(createHash("sha1").update(data).digest()), new Uint8Array(info.digest));
        assert.equal(Number(info.materialized_length), data.length);
      }
    }
  }
  const files = new Set([...infos.values()].filter((i) => i.file_name).map((i) => "Data/" + i.file_name));
  for (const n of p.filenames) if (n.startsWith("Data/")) assert.ok(files.has(n), `${n} isn't listed`);
}
