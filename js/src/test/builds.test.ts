import { test } from "node:test";
import assert from "node:assert/strict";

import { Presentation, fromMarkdown } from "../index.js";
import type { Message } from "../protobuf.js";
import { checkConsistent, fixture, reopen } from "./helpers.js";

test("read builds from a Keynote file", async () => {
  const deck = await fixture("builds-talk.key");
  const [body, shape] = deck.slide(0).builds;
  assert.deepEqual(body, {
    target: "body",
    kind: "in",
    effect: "dissolve",
    delivery: "By Paragraph",
    duration: 1.0,
    steps: 3,
    effectId: "apple:dissolve character",
    start: "on click",
    delay: 0,
    direction: null,
  });
  assert.equal(typeof shape.target, "number");
  assert.deepEqual([shape.effect, shape.delivery, shape.steps], ["move in", "All at Once", 1]);
  assert.deepEqual(deck.slide(1).builds, []);
});

test("add builds", async () => {
  const deck = await Presentation.create();
  const slide = deck.addSlide("Title & Bullets", { title: "Builds", body: "One\nTwo\n\nThree" });
  slide.addBuild("title", { effect: "move in", duration: 0.5 });
  slide.addBuild("body", "dissolve");
  const again = await reopen(deck);
  const [title, body] = again.slide(0).builds;
  assert.deepEqual([title.target, title.effect, title.delivery, title.duration, title.steps], ["title", "move in", "All at Once", 0.5, 1]);
  assert.deepEqual([body.target, body.effect, body.delivery, body.steps], ["body", "dissolve", "By Paragraph", 3]);
  assert.equal(again.slide(0).node.build_event_count, 4);
  checkConsistent(again);
});

test("builds are listed in play order", async () => {
  // Keynote 14.5 reorders SlideArchive.builds on save but keeps the chunks in play order.
  const deck = await Presentation.create();
  const slide = deck.addSlide("Title & Bullets", { title: "T", body: "a\nb" });
  slide.addBuild("title", "move in");
  slide.addBuild("body", "dissolve");
  slide.slide.builds = [...(slide.slide.builds as Message[])].reverse();
  assert.deepEqual(slide.builds.map((b) => b.target), ["title", "body"]);
});

test("build all at once, and out", async () => {
  const deck = await Presentation.create();
  const slide = deck.addSlide("Title & Bullets", { title: "T", body: "a\nb" });
  slide.addBuild("body", { effect: "dissolve", delivery: "all at once", kind: "out" });
  const b = (await reopen(deck)).slide(0).builds[0];
  assert.deepEqual([b.kind, b.delivery, b.steps], ["out", "All at Once", 1]);
});

test("build errors", async () => {
  const deck = await Presentation.create();
  const slide = deck.addSlide("Title Only", { title: "T" });
  assert.throws(() => slide.addBuild("body"), /doesn't show a body/);
  assert.throws(() => slide.addBuild("title", { delivery: "sideways" }), /delivery/);
  assert.throws(() => slide.addBuild("title", { kind: "sideways" as "in" }), /kind/);
});

test("clear builds", async () => {
  const deck = await fixture("builds-talk.key");
  deck.slide(0).clearBuilds();
  const again = await reopen(deck);
  assert.deepEqual(again.slide(0).builds, []);
  assert.equal(again.slide(0).node.build_event_count, 0);
  assert.equal([...again.package.objects("KN.BuildArchive")].length, 0);
  checkConsistent(again);
});

test("duplicating a slide copies its builds with new ids", async () => {
  const deck = await fixture("builds-talk.key");
  deck.duplicateSlide(0);
  const again = await reopen(deck);
  assert.deepEqual(again.slides.map((s) => s.builds.length), [2, 2, 0]);
  const uuids = new Set([...again.package.objects("KN.BuildChunkArchive")].map(([, c]) => `${c.build_id.lower}:${c.build_id.upper}`));
  assert.equal(uuids.size, 4); // two builds per slide, none shared between the copies
  checkConsistent(again);
});

test("builds in Markdown", async () => {
  const md = (await fixture("builds-talk.key")).toMarkdown();
  assert.ok(md.includes("<!-- build: body, dissolve, by bullet, 1s -->"));
  const again = await reopen(await fromMarkdown(md));
  assert.equal(again.toMarkdown(), md);
});

test("Markdown build options", async () => {
  const deck = await fromMarkdown(`<!-- build: title, move in, 0.5s -->
<!-- build: body, dissolve, all at once, out -->
# Hello

- a
- b
`);
  const [title, body] = (await reopen(deck)).slide(0).builds;
  assert.deepEqual([title.effect, title.duration], ["move in", 0.5]);
  assert.deepEqual([body.delivery, body.kind], ["All at Once", "out"]);
});

test("applyTheme keeps builds on the title and body", async () => {
  const deck = await fixture("builds-talk.key");
  await deck.applyTheme("Basic Black");
  const again = await reopen(deck);
  assert.deepEqual(
    again.slide(0).builds.map((b) => [b.target, b.effect, b.delivery, b.steps]),
    [["body", "dissolve", "By Paragraph", 3]],
  );
});
