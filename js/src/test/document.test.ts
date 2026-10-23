import { test } from "node:test";
import assert from "node:assert/strict";

import { fixture, tmpPath } from "./helpers.js";
import { Presentation } from "../index.js";

export const BASIC_WHITE_LAYOUTS = [
  "Title", "Title & Photo", "Title & Photo Alt", "Title & Bullets", "Bullets",
  "Title, Bullets & Photo", "Title, Bullets & Live Video Small",
  "Title, Bullets & Live Video Large", "Section", "Title Only", "Agenda",
  "Statement", "Big Fact", "Quote", "Photo - 3 Up", "Photo", "Blank",
];

test("presentation basics", async () => {
  const deck = await fixture("layouts-basic-white.key");
  assert.equal(deck.length, 17);
  assert.equal(deck.theme, "Basic White");
  assert.deepEqual(deck.layouts, BASIC_WHITE_LAYOUTS);
  assert.deepEqual(deck.size, { width: 1024, height: 768 });
  assert.deepEqual([...deck].map((s) => s.layout), BASIC_WHITE_LAYOUTS);
});

test("title shown only where the layout has one", async () => {
  const deck = await fixture("layouts-basic-white.key");
  const titles = new Map(deck.slides.map((s) => [s.layout, s.title]));
  assert.equal(titles.get("Title & Bullets"), "Title & Bullets");
  assert.equal(titles.get("Section"), "Section");
  for (const layout of ["Bullets", "Statement", "Quote", "Blank", "Photo"]) assert.equal(titles.get(layout), null);
});

test("body and bullets", async () => {
  const deck = await fixture("layouts-basic-white.key");
  const slide = deck.slide(3);
  assert.equal(slide.body, "First bullet\nSecond bullet\nThird bullet");
  assert.deepEqual(slide.paragraphs, [
    { text: "First bullet", level: 0, bulleted: true },
    { text: "Second bullet", level: 0, bulleted: true },
    { text: "Third bullet", level: 0, bulleted: true },
  ]);
  assert.equal(deck.slide(11).layout, "Statement");
  assert.ok(!deck.slide(11).paragraphs.some((p) => p.bulleted));
  assert.equal(deck.slide(8).body, null);
  assert.equal(deck.slide(-1).layout, "Blank");
});

test("notes", async () => {
  const deck = await fixture("layouts-basic-white.key");
  assert.deepEqual(deck.slides.map((s) => s.notes), BASIC_WHITE_LAYOUTS.map((n) => `Notes for ${n}`));
});

test("transitions", async () => {
  const deck = await fixture("transitions-basic-white.key");
  assert.deepEqual(
    deck.slides.map((s) => [s.title, s.transition.effect, s.transition.duration]),
    [["Dissolve", "dissolve", 1.5], ["Push", "push", 1.5], ["Magic Move", "magic move", 1.5], ["None", null, 1.0]],
  );
  assert.equal(deck.slide(0).transition.effectId, "apple:dissolve");
});

for (const [name, theme, count] of [
  ["blank-basic-white.key", "Basic White", 17],
  ["blank-basic-black.key", "Basic Black", 17],
  ["blank-white.key", "White", 14],
] as const) {
  test(`blank deck ${name}`, async () => {
    const deck = await fixture(name);
    assert.equal(deck.length, 1);
    assert.equal(deck.theme, theme);
    assert.equal(deck.layouts.length, count);
  });
}

test("an unchanged save is identical", async () => {
  const deck = await fixture("transitions-basic-white.key");
  const out = tmpPath("copy.key");
  await deck.save(out);
  const again = await Presentation.open(out);
  assert.deepEqual(again.slides.map((s) => s.toJSON()), deck.slides.map((s) => s.toJSON()));
  assert.deepEqual(again.package.filenames, deck.package.filenames);
  for (const name of again.package.filenames) assert.deepEqual(again.package.readFile(name), deck.package.readFile(name));
});

test("toJSON", async () => {
  const deck = await fixture("layouts-basic-white.key");
  assert.deepEqual(deck.slide(3).toJSON(), {
    index: 3,
    layout: "Title & Bullets",
    title: "Title & Bullets",
    body: "First bullet\nSecond bullet\nThird bullet",
    notes: "Notes for Title & Bullets",
    skipped: false,
    transition: { effect: null, duration: 1.0, delay: 0.5, automatic: false },
  });
});
