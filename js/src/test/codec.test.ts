import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import assert from "node:assert/strict";
import { unzipSync } from "fflate";

import { concat, parseIwa, serializeIwa, serializeSegment } from "../iwa.js";
import { create, decode, encode } from "../protobuf.js";
import { compress, uncompress } from "../snappy.js";
import { FIXTURES } from "./helpers.js";

function rawStream(data: Uint8Array): Uint8Array {
  const parts: Uint8Array[] = [];
  for (let pos = 0; pos < data.length; ) {
    const len = data[pos + 1] | (data[pos + 2] << 8) | (data[pos + 3] << 16);
    parts.push(uncompress(data.subarray(pos + 4, pos + 4 + len)));
    pos += 4 + len;
  }
  return concat(parts);
}

test("snappy round trip", () => {
  const text = new TextEncoder().encode("robots ".repeat(5000) + "and some other words to vary it");
  const random = new Uint8Array(70000);
  for (let i = 0; i < random.length; i++) random[i] = (i * 2654435761) >>> 24;
  for (const input of [new Uint8Array(0), Uint8Array.of(1, 2, 3), text, random]) {
    const packed = compress(input);
    assert.deepEqual(uncompress(packed), input);
  }
  assert.ok(compress(text).length < text.length / 10);
});

test("re-encoding archives gives Keynote's exact bytes", () => {
  const files = unzipSync(readFileSync(join(FIXTURES, "layouts-basic-white.key")));
  for (const [name, data] of Object.entries(files)) {
    if (!name.endsWith(".iwa")) continue;
    const mine = concat(parseIwa(data, name).map(serializeSegment));
    assert.deepEqual(mine, rawStream(data), name);
    assert.deepEqual(rawStream(serializeIwa(parseIwa(data, name))), rawStream(data), name);
  }
});

test("64-bit values and unknown fields survive", () => {
  const big = 2n ** 63n + 5n;
  const uuid = create("TSP.UUID", { lower: big, upper: 7 });
  const again = decode("TSP.UUID", encode(uuid));
  assert.equal(again.lower, big);
  assert.equal(again.upper, 7);
  // Field 15 isn't in TSP.UUID: it is kept as raw bytes and written back.
  const withExtra = concat([encode(uuid), Uint8Array.of(15 << 3, 42)]);
  assert.deepEqual(encode(decode("TSP.UUID", withExtra)), withExtra);
});

test("absent fields read as defaults", () => {
  const ref = create("TSP.Reference");
  assert.equal(ref.identifier, 0);
  assert.deepEqual(Object.keys(ref), []);
  const node = create("KN.SlideNodeArchive");
  assert.equal(node.depth, 1);
  node.children.push(create("TSP.Reference", { identifier: 3 }));
  assert.equal(decode("KN.SlideNodeArchive", encode(node)).children[0].identifier, 3);
});
