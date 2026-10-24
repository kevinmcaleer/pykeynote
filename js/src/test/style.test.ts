import { test } from "node:test";
import assert from "node:assert/strict";

import { Presentation, fromMarkdown } from "../index.js";
import type { Message } from "../protobuf.js";
import { checkConsistent, fixture, reopen } from "./helpers.js";

async function styleCheckDeck(): Promise<Presentation> {
  const deck = await Presentation.create();
  const s = deck.addSlide("Title & Bullets", { title: "test", body: ["some text", "more points", "last bits"] });
  s.addSubtitle("sub title");
  s.setTransition("wipe", { duration: 0.75 });
  s.addBuild("title", { effect: "wipe", direction: "from left" });
  s.addBuild("subtitle", { effect: "wipe", direction: "from left", start: "after previous", delay: 0.1 });
  s.addBuild("body", { effect: "fade and move", delivery: "by bullet", duration: 0.3 });
  return deck;
}

test("the style check deck reads back", async () => {
  const again = await reopen(await styleCheckDeck());
  const s = again.slide(0);
  assert.equal(s.subtitle, "sub title");
  const t = s.transition;
  assert.deepEqual([t.effect, t.effectId, t.duration, t.direction], ["wipe", "apple:wipe", 0.75, "from left"]);
  assert.deepEqual(
    s.builds.map((b) => [b.target, b.effectId, b.delivery, b.duration, b.steps, b.start, b.delay, b.direction]),
    [
      ["title", "apple:wipe", "All at Once", 1, 1, "on click", 0, "from left"],
      ["subtitle", "apple:wipe", "All at Once", 1, 1, "after previous", 0.1, "from left"],
      ["body", "apple:fade and move character", "By Paragraph", 0.3, 3, "on click", 0, null],
    ],
  );
  const chunks = (s.slide.buildChunks as Message[]).map((r) => s.pkg.deref(r));
  assert.deepEqual(
    chunks.map((c) => [Boolean(c.automatic), c.delay]),
    [[false, 0], [true, 0.1], [false, 0], [false, 0], [false, 0]],
  );
  checkConsistent(again);
});

test("directions are written and read back", async () => {
  for (const [name, value] of [["from right", 12], ["from top", 13], ["bottom to top", 14]] as const) {
    const deck = await Presentation.create();
    const s = deck.addSlide("Title & Bullets", { title: "T", body: "a" });
    s.setTransition("wipe", { direction: name });
    s.addBuild("title", { effect: "wipe", direction: name });
    s.addBuild("body", { effect: "fade-and-move", direction: name });
    const again = (await reopen(deck)).slide(0);
    assert.equal(again.slide.transition.attributes.animationAttributes.direction, value);
    assert.equal(again.builds[0].direction, again.transition.direction);
    assert.equal(again.builds[1].direction, again.transition.direction);
  }
  const deck = await Presentation.create();
  const s = deck.addSlide("Title & Bullets", { title: "T", body: "a" });
  assert.throws(() => s.addBuild("title", { effect: "dissolve", direction: "from left" }), /'?"dissolve" build has no direction/);
  assert.throws(() => s.addBuild("title", { effect: "wipe", start: "whenever" }), /start must be one of/);
});

test("subtitles fill the layout's box or add one", async () => {
  const deck = await Presentation.create();
  const bullets = deck.addSlide("Title & Bullets", { title: "T", body: "a" });
  assert.equal(bullets.subtitle, null);
  const count = bullets.drawables.length;
  bullets.addSubtitle("sub");
  assert.equal(bullets.drawables.length, count);
  const section = deck.addSlide("Section", { title: "S" });
  assert.ok(section.addSubtitle("added").isSubtitle);
  assert.throws(() => section.addSubtitle("again"), /already has a subtitle/);
  const again = await reopen(deck);
  assert.deepEqual(again.slides.map((s) => s.subtitle), ["sub", "added"]);
  checkConsistent(again);
});

test("Markdown round trip", async () => {
  const md = (await styleCheckDeck()).toMarkdown();
  assert.ok(md.includes("<!-- transition: wipe 0.75s from left -->"));
  assert.ok(md.includes("<!-- build: subtitle, wipe, all at once, 1s, after previous, delay 0.1s, from left -->"));
  assert.ok(md.includes("# test\n## sub title\n"));
  const again = await reopen(await fromMarkdown(md));
  assert.equal(again.toMarkdown(), md);
});

test("Markdown matches the Python library's output", async () => {
  const md = `<!-- transition: wipe 0.75s from-right -->
<!-- build: title, wipe, 1s, from left -->
<!-- build: subtitle, wipe, 1s, after-previous, delay 0.1s -->
<!-- build: body, fade and move, by bullet, 0.3s -->
# test
## sub title

- a
- b
`;
  const s = (await reopen(await fromMarkdown(md))).slide(0);
  assert.equal(s.transition.direction, "from right");
  assert.deepEqual(s.builds.map((b) => [b.target, b.start, b.delay]), [
    ["title", "on click", 0],
    ["subtitle", "after previous", 0.1],
    ["body", "on click", 0],
  ]);
});

test("applyStyle styles every slide", async () => {
  const deck = await Presentation.create();
  deck.addSlide("Title", { title: "Hello" });
  deck.addSlide("Title & Bullets", { title: "test", body: ["a", "b"] }).addSubtitle("sub");
  deck.addSlide("Blank");
  deck.applyStyle({
    transition: { effect: "wipe", duration: 0.75 },
    titleBuild: { effect: "wipe", direction: "from left" },
    subtitleBuild: { effect: "wipe", start: "after previous", delay: 0.1 },
    bodyBuild: { effect: "fade and move", delivery: "by bullet", duration: 0.3 },
  });
  const again = await reopen(deck);
  assert.deepEqual(again.slides.map((s) => s.transition.effect), ["wipe", "wipe", "wipe"]);
  assert.deepEqual(again.slides.map((s) => s.builds.map((b) => b.target)), [["title"], ["title", "subtitle", "body"], []]);
  checkConsistent(again);
});

test("applyTheme keeps the style", async () => {
  const deck = await styleCheckDeck();
  const before = deck.slide(0).toJSON().builds;
  await deck.applyTheme("Basic Black");
  const s = (await reopen(deck)).slide(0);
  assert.equal(s.subtitle, "sub title");
  assert.deepEqual(s.toJSON().builds, before);
});

// builds-timing.key was made by hand in Keynote 14.5.
function chunks(slide: ReturnType<Presentation["slide"]>): [boolean, boolean, number][] {
  return (slide.slide.buildChunks as Message[]).map((r) => {
    const c = slide.pkg.deref(r);
    return [Boolean(c.automatic), Boolean(c.referent), Math.round((c.delay ?? 0) * 1e6) / 1e6];
  });
}

test("read the Keynote timing fixture", async () => {
  const deck = await fixture("builds-timing.key");
  const s = deck.slide(0);
  assert.equal(s.subtitle, "subtitle");
  assert.deepEqual(
    s.builds.map((b) => [b.target, b.effect, b.delivery, Math.round(b.duration * 1e6) / 1e6, b.steps, b.start, b.delay, b.direction]),
    [
      ["title", "wipe", "All at Once", 1, 1, "on click", 0, "from left"],
      ["subtitle", "wipe", "All at Once", 1, 1, "with previous", 0.1, "from left"],
      ["body", "fade and move", "By Paragraph", 0.3, 4, "after previous", 0, null],
    ],
  );
  assert.deepEqual([3, 4, 5].map((i) => deck.slide(i).builds[0].direction), ["from right", "from top", "from bottom"]);
  assert.deepEqual([6, 7, 8, 9].map((i) => deck.slide(i).transition.direction), ["from left", "from right", "from top", "from bottom"]);
});

test("timing is written as Keynote writes it", async () => {
  const keynote = await fixture("builds-timing.key");
  const deck = await Presentation.create();
  const s = deck.addSlide("Title & Bullets", { title: "title", body: ["a", "b", "c", "d"] });
  s.addSubtitle("subtitle");
  s.addBuild("title", "wipe");
  s.addBuild("subtitle", { effect: "wipe", start: "with previous", delay: 0.1 });
  s.addBuild("body", { effect: "fade and move", delivery: "by bullet", duration: 0.3, start: "after previous" });
  const again = await reopen(deck);
  assert.deepEqual(chunks(again.slide(0)), chunks(keynote.slide(0)));
});
