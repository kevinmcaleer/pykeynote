import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";

import { Presentation } from "../index.js";
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
