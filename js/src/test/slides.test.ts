import { test } from "node:test";
import assert from "node:assert/strict";

import { checkConsistent, fixture, reopen, tmpPath } from "./helpers.js";
import { Presentation, fromMarkdown, parseMarkdown, themes } from "../index.js";
import type { Message } from "../protobuf.js";

const layoutsOf = (deck: Presentation) => deck.slides.map((s) => s.layout);

test("move a slide", async () => {
  const deck = await fixture("layouts-basic-white.key");
  const before = layoutsOf(deck);
  deck.moveSlide(3, 0);
  const again = await reopen(deck);
  assert.deepEqual(layoutsOf(again), [before[3], ...before.slice(0, 3), ...before.slice(4)]);
  checkConsistent(again);
});

test("delete slides", async () => {
  const deck = await fixture("layouts-basic-white.key");
  const before = layoutsOf(deck);
  deck.deleteSlide(3);
  deck.deleteSlide(-1);
  const again = await reopen(deck);
  assert.deepEqual(layoutsOf(again), [...before.slice(0, 3), ...before.slice(4, -1)]);
  checkConsistent(again);
});

test("deleting the selected slide moves the selection", async () => {
  const deck = await fixture("transitions-basic-white.key");
  deck.deleteSlide(3); // Keynote saved this file with the last slide selected
  const again = await reopen(deck);
  const showId: number = (again as any).showId;
  const remaining = new Set((again.package.get(showId).slideTree.slides as Message[]).map((r) => r.identifier));
  for (const [, obj] of again.package.objects("KN.SlideCollectionSelectionArchive")) {
    for (const r of obj.slide_nodes as Message[]) assert.ok(remaining.has(r.identifier));
  }
});

test("can't delete the last slide", async () => {
  const deck = await fixture("blank-basic-white.key");
  assert.throws(() => deck.deleteSlide(0));
});

test("duplicate a slide", async () => {
  const deck = await fixture("layouts-basic-white.key");
  const copy = deck.duplicateSlide(3);
  copy.title = "The copy";
  const again = await reopen(deck);
  assert.equal(again.length, 18);
  assert.equal(again.slide(3).title, "Title & Bullets");
  assert.equal(again.slide(4).title, "The copy");
  assert.equal(again.slide(4).body, again.slide(3).body);
  assert.equal(again.slide(4).layout, "Title & Bullets");
  checkConsistent(again);
});

test("duplicate, then delete the original", async () => {
  const deck = await fixture("layouts-basic-white.key");
  deck.duplicateSlide(3, 0);
  deck.deleteSlide(4);
  const again = await reopen(deck);
  assert.equal(again.slide(0).layout, "Title & Bullets");
  assert.equal(layoutsOf(again).filter((l) => l === "Title & Bullets").length, 1);
  checkConsistent(again);
});

test("new presentation", async () => {
  assert.ok(themes().includes("Basic White"));
  const deck = await Presentation.create();
  assert.equal(deck.length, 0);
  deck.addSlide("Title", { title: "Robots!", body: "Kevin McAleer" });
  deck.addSlide("Title & Bullets", {
    title: "Why robots?",
    body: [{ text: "Fun" }, { text: "Mostly", level: 1 }, "Useful"],
    notes: "Short one",
  });
  deck.addSlide("Blank");
  const again = await reopen(deck);
  assert.deepEqual(layoutsOf(again), ["Title", "Title & Bullets", "Blank"]);
  assert.equal(again.slide(0).title, "Robots!");
  assert.equal(again.slide(0).body, "Kevin McAleer");
  assert.deepEqual(again.slide(1).paragraphs.map((p) => [p.text, p.level]), [["Fun", 0], ["Mostly", 1], ["Useful", 0]]);
  assert.equal(again.slide(1).notes, "Short one");
  assert.equal(again.slide(2).notes, "");
  checkConsistent(again);
});

test("a new presentation keeps working after saving", async () => {
  const deck = await Presentation.create();
  deck.addSlide("Title Only", { title: "One" });
  await deck.save(tmpPath("a.key"));
  deck.addSlide("Title Only", { title: "Two" });
  const again = await reopen(deck, "b.key");
  assert.deepEqual(again.slides.map((s) => s.title), ["One", "Two"]);
});

test("a new presentation needs a slide", async () => {
  const deck = await Presentation.create();
  await assert.rejects(deck.save(tmpPath("empty.key")));
});

test("addSlide errors", async () => {
  const deck = await fixture("layouts-basic-white.key");
  assert.throws(() => deck.addSlide("Nonexistent"), /no slide uses/);
  assert.throws(() => deck.addSlide("Bullets", { title: "No title here" }), /doesn't show a title/);
});

test("addSlide at an index", async () => {
  const deck = await fixture("layouts-basic-white.key");
  deck.addSlide("Section", { title: "Part two", index: 1 });
  const again = await reopen(deck);
  assert.equal(again.slide(1).title, "Part two");
  assert.equal(again.slide(1).layout, "Section");
});

test("transitions and skipping", async () => {
  const deck = await fixture("transitions-basic-white.key");
  deck.slide(3).setTransition("magic move", { duration: 2 });
  deck.slide(0).setTransition(null);
  deck.slide(1).skipped = true;
  const again = await reopen(deck);
  assert.deepEqual(
    again.slides.map((s) => [s.transition.effect, s.transition.duration, s.skipped]),
    [[null, 1.5, false], ["push", 1.5, true], ["magic move", 1.5, false], ["magic move", 2.0, false]],
  );
  assert.equal(again.slide(3).transition.effectId, "apple:magic-move-implied-motion-path");
});

test("markdown round trip", async () => {
  for (const name of ["layouts-basic-white.key", "transitions-basic-white.key", "layouts-basic-white-wide.key"]) {
    const md = (await fixture(name)).toMarkdown();
    const again = await reopen(await fromMarkdown(md), name);
    assert.equal(again.toMarkdown(), md);
    checkConsistent(again);
  }
});

test("markdown without layouts", async () => {
  const md = `# Robots!

Kevin McAleer

---

# Why robots?

- Fun
  - Mostly
- Useful

???
Keep it short.

---

<!-- transition: dissolve 1s -->
<!-- skipped -->
# Thanks

---

- Just bullets
`;
  const again = await reopen(await fromMarkdown(md));
  assert.deepEqual(layoutsOf(again), ["Title", "Title & Bullets", "Title Only", "Bullets"]);
  assert.equal(again.slide(1).notes, "Keep it short.");
  assert.deepEqual(again.slide(1).paragraphs.map((p) => [p.text, p.level]), [["Fun", 0], ["Mostly", 1], ["Useful", 0]]);
  assert.equal(again.slide(2).transition.effect, "dissolve");
  assert.equal(again.slide(2).transition.duration, 1.0);
  assert.ok(again.slide(2).skipped);
});

test("parseMarkdown details", () => {
  const specs = parseMarkdown(`<!-- layout: Quote -->
A long
quote over lines

\\# not a heading

---

\`\`\`
---
\`\`\`
`);
  assert.equal(specs.length, 2);
  assert.equal(specs[0].layout, "Quote");
  assert.deepEqual(specs[0].paragraphs.map((p) => p.text), ["A long quote over lines", "# not a heading"]);
});

for (const [aspect, size] of [["16:9", { width: 1920, height: 1080 }], ["4:3", { width: 1024, height: 768 }]] as const) {
  test(`new presentation at ${aspect}`, async () => {
    const deck = await Presentation.create({ aspect });
    deck.addSlide("Title & Bullets", { title: "Shape", body: "One\nTwo" });
    const again = await reopen(deck);
    assert.deepEqual(again.size, size);
    assert.equal(again.slide(0).title, "Shape");
    checkConsistent(again);
  });
}

test("new presentations default to widescreen", async () => {
  assert.deepEqual((await Presentation.create()).size, { width: 1920, height: 1080 });
  assert.deepEqual((await fromMarkdown("# Hi")).size, { width: 1920, height: 1080 });
  assert.deepEqual((await fromMarkdown("# Hi", { aspect: "4:3" })).size, { width: 1024, height: 768 });
});

test("a bad aspect is refused", async () => {
  await assert.rejects(Presentation.create({ aspect: "21:9" as any }), /aspect/);
});
