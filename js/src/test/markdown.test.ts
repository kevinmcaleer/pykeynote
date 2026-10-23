import { test } from "node:test";
import assert from "node:assert/strict";

import { fixture } from "./helpers.js";

test("transitions deck to markdown", async () => {
  const md = (await fixture("transitions-basic-white.key")).toMarkdown();
  assert.equal(
    md,
    "<!-- layout: Title & Bullets -->\n" +
      "<!-- transition: dissolve 1.5s -->\n" +
      "# Dissolve\n" +
      "\n---\n\n" +
      "<!-- layout: Title & Bullets -->\n" +
      "<!-- transition: push 1.5s -->\n" +
      "# Push\n" +
      "\n---\n\n" +
      "<!-- layout: Title & Bullets -->\n" +
      "<!-- transition: magic move 1.5s -->\n" +
      "# Magic Move\n" +
      "\n---\n\n" +
      "<!-- layout: Title & Bullets -->\n" +
      "# None\n",
  );
});

test("bullets and notes", async () => {
  const blocks = (await fixture("layouts-basic-white.key")).toMarkdown().split("\n---\n\n");
  assert.equal(blocks.length, 17);
  assert.equal(
    blocks[3],
    "<!-- layout: Title & Bullets -->\n" +
      "# Title & Bullets\n" +
      "\n" +
      "- First bullet\n" +
      "- Second bullet\n" +
      "- Third bullet\n" +
      "\n" +
      "???\n" +
      "Notes for Title & Bullets\n",
  );
  // Statement's body has no bullets, so its paragraphs are plain text.
  assert.ok(blocks[11].includes("\nFirst bullet\n\nSecond bullet\n"));
});
