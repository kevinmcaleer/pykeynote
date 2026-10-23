import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

// Bundlers take the library as it is only if nothing it loads imports Node's modules up front.
test("the library has no static imports of Node modules", () => {
  const dist = fileURLToPath(new URL("../", import.meta.url));
  const offenders = readdirSync(dist)
    .filter((name) => name.endsWith(".js"))
    .filter((name) => /^\s*(import|export)\b[^;]*from\s*["']node:/m.test(readFileSync(dist + name, "utf8")));
  assert.deepEqual(offenders, []);
});
