import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { test } from "node:test";
import assert from "node:assert/strict";

import { FIXTURES, fixture, reopen, tmpPath } from "./helpers.js";
import { Presentation, UnsupportedTextError, type Text } from "../index.js";
import { create, type Message } from "../protobuf.js";

/** The invariants Keynote relies on: para styles line up with paragraph starts. */
function checkTables(text: Text | null): void {
  assert.ok(text);
  const st: Message = (text as any).storage;
  const raw = text.raw;
  const chunks = raw ? raw.split("\r") : [""];
  const starts: number[] = [];
  let offset = 0;
  for (const c of chunks) {
    starts.push(offset);
    offset += c.length + 1;
  }
  assert.deepEqual(st.table_para_style.entries.map((e: Message) => e.character_index), starts);
  for (const name of ["table_para_data", "table_list_style", "table_para_starts", "table_para_bidi"]) {
    const indexes: number[] = st[name].entries.map((e: Message) => e.character_index);
    assert.equal(indexes[0], 0);
    for (const i of indexes) assert.ok(starts.includes(i), name);
  }
}

test("set a title", async () => {
  const deck = await fixture("layouts-basic-white.key");
  deck.slide(3).title = "Robots are great 🤖";
  const again = await reopen(deck);
  assert.equal(again.slide(3).title, "Robots are great 🤖");
  assert.equal(again.slide(3).body, "First bullet\nSecond bullet\nThird bullet");
  assert.equal(again.slide(4).body, deck.slide(4).body);
  checkTables(again.slide(3).titleText);
});

test("set a body with more paragraphs and emoji", async () => {
  const deck = await fixture("layouts-basic-white.key");
  deck.slide(3).body = "🚀 One\nTwo\nThree\nFour\nFive";
  const again = await reopen(deck);
  const paras = again.slide(3).paragraphs;
  assert.deepEqual(paras.map((p) => p.text), ["🚀 One", "Two", "Three", "Four", "Five"]);
  assert.ok(paras.every((p) => p.bulleted));
  checkTables(again.slide(3).bodyText);
});

test("set a body with fewer paragraphs", async () => {
  const deck = await fixture("layouts-basic-white.key");
  deck.slide(3).body = "Only one";
  const again = await reopen(deck);
  assert.deepEqual(again.slide(3).paragraphs, [{ text: "Only one", level: 0, bulleted: true }]);
  checkTables(again.slide(3).bodyText);
});

test("indent levels", async () => {
  const deck = await fixture("layouts-basic-white.key");
  deck.slide(3).body = [{ text: "Top" }, { text: "Nested", level: 1 }, { text: "Deeper", level: 2 }, "Inherits"];
  const again = await reopen(deck);
  assert.deepEqual(
    again.slide(3).paragraphs.map((p) => [p.text, p.level]),
    [["Top", 0], ["Nested", 1], ["Deeper", 2], ["Inherits", 0]],
  );
  checkTables(again.slide(3).bodyText);
});

test("line break inside a paragraph", async () => {
  const deck = await fixture("layouts-basic-white.key");
  deck.slide(3).body = [{ text: "Line one\nline two" }];
  const again = await reopen(deck);
  assert.equal(again.slide(3).paragraphs[0].text, "Line one\nline two");
  assert.equal(again.slide(3).paragraphs.length, 1);
});

test("empty body", async () => {
  const deck = await fixture("layouts-basic-white.key");
  deck.slide(3).body = "";
  const again = await reopen(deck);
  assert.equal(again.slide(3).body, "");
  assert.deepEqual(again.slide(3).paragraphs, []);
  checkTables(again.slide(3).bodyText);
});

test("fill an empty placeholder", async () => {
  const deck = await fixture("transitions-basic-white.key");
  assert.equal(deck.slide(0).body, "");
  deck.slide(0).body = "Now\nwith\nbullets";
  const again = await reopen(deck);
  assert.equal(again.slide(0).body, "Now\nwith\nbullets");
  checkTables(again.slide(0).bodyText);
});

test("notes", async () => {
  const deck = await fixture("layouts-basic-white.key");
  deck.slide(0).notes = "Say hello\nThen start";
  const again = await reopen(deck);
  assert.equal(again.slide(0).notes, "Say hello\nThen start");
});

test("a hidden placeholder refuses text", async () => {
  const deck = await fixture("layouts-basic-white.key");
  assert.throws(() => {
    deck.slide(4).title = "Bullets has no title";
  }, /doesn't show a title/);
});

test("bad characters are refused", async () => {
  const deck = await fixture("layouts-basic-white.key");
  assert.throws(() => {
    deck.slide(3).body = [{ text: "a\rb" }];
  });
});

test("anchored objects are refused", async () => {
  const deck = await fixture("layouts-basic-white.key");
  const text = deck.slide(3).bodyText!;
  const st: Message = (text as any).storage;
  st.table_attachment = create("TSWP.ObjectAttributeTable", { entries: [create("TSWP.ObjectAttributeTable.ObjectAttribute", { character_index: 0 })] });
  assert.throws(() => text.setParagraphs(["x"]), UnsupportedTextError);
});

test("only changed files are rewritten", async () => {
  const deck = await fixture("layouts-basic-white.key");
  deck.slide(3).title = "Changed";
  const again = await reopen(deck);
  const original = await fixture("layouts-basic-white.key");
  const changed = original.package.filenames.filter(
    (n) => Buffer.compare(original.package.readFile(n), again.package.readFile(n)) !== 0,
  );
  const slideFile = original.package.fileOf((original.slide(3) as any).slideId);
  assert.ok(changed.includes(slideFile));
  for (const n of changed) assert.ok([slideFile, "Index/Document.iwa"].includes(n), n);
});

test("save in place", async () => {
  const path = tmpPath("deck.key");
  await writeFile(path, await readFile(join(FIXTURES, "transitions-basic-white.key")));
  const deck = await Presentation.open(path);
  deck.slide(1).title = "Pushed";
  await deck.save();
  assert.equal((await Presentation.open(path)).slide(1).title, "Pushed");
});
