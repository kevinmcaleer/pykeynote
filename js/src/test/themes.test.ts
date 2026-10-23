import { test } from "node:test";
import assert from "node:assert/strict";

import { checkConsistent, fixture, reopen } from "./helpers.js";
import { Presentation, fromMarkdown, themes } from "../index.js";

const otherTheme = (than: string): string => themes().find((t) => t !== than) ?? than;
const SIZES = { "16:9": { width: 1920, height: 1080 }, "4:3": { width: 1024, height: 768 } } as const;

for (const theme of themes()) {
  for (const aspect of ["16:9", "4:3"] as const) {
    test(`bundled theme ${theme} (${aspect})`, async () => {
      const deck = await Presentation.create({ theme, aspect });
      assert.equal(deck.theme, theme);
      assert.deepEqual(deck.size, SIZES[aspect]);
      for (const [title, body] of [[true, true], [true, false], [false, true], [false, false]]) {
        deck.addSlide(deck.matchLayout("Nonexistent", title, body), {
          title: title ? "Title" : undefined,
          body: body ? "One\nTwo" : undefined,
        });
      }
      const again = await reopen(deck);
      assert.equal(again.theme, theme);
      assert.deepEqual(again.slides.map((s) => s.title), ["Title", "Title", null, null]);
      assert.deepEqual(again.slides.map((s) => s.body), ["One\nTwo", null, "One\nTwo", null]);
      checkConsistent(again);
    });
  }
}

test("match layouts", async () => {
  const deck = await Presentation.create();
  assert.equal(deck.matchLayout("Agenda", true, true), "Agenda");
  assert.equal(deck.matchLayout("Bullets", true, true), "Title & Bullets");
  assert.equal(deck.matchLayout("Fancy", true), "Title Only");
  assert.equal(deck.matchLayout("Fancy", false, true), "Bullets");
  assert.equal(deck.matchLayout("Fancy"), "Blank");
});

test("apply a theme, keeping the content", async () => {
  const deck = await fixture("builds-talk.key");
  const summary = (d: Presentation) =>
    d.slides.map((s) => [s.layout, s.title, s.paragraphs.map((p) => [p.text, p.level]), s.notes, s.transition, s.skipped]);
  const before = summary(deck);
  const theme = otherTheme(deck.theme);
  await deck.applyTheme(theme, { aspect: "4:3" });
  const again = await reopen(deck);
  assert.equal(again.theme, theme);
  assert.deepEqual(again.size, SIZES["4:3"]);
  assert.deepEqual(summary(again), before);
  checkConsistent(again);
});

test("apply a theme with a layout map", async () => {
  const deck = await Presentation.create({ aspect: "4:3" });
  deck.addSlide("Title & Bullets", { title: "A", body: [{ text: "x" }, { text: "y", level: 1 }] });
  deck.addSlide("Quote", { body: "To be or not to be" });
  await deck.applyTheme(otherTheme("Basic White"), { layouts: { Quote: "Statement" } });
  assert.deepEqual(deck.size, SIZES["4:3"]);
  assert.deepEqual(deck.slides.map((s) => s.layout), ["Title & Bullets", "Statement"]);
  deck.addSlide("Title Only", { title: "More" });
  const again = await reopen(deck);
  assert.deepEqual(again.slides.map((s) => s.title), ["A", null, "More"]);
  assert.deepEqual(again.slides[0].paragraphs.map((p) => [p.text, p.level]), [["x", 0], ["y", 1]]);
  checkConsistent(again);
  await assert.rejects(deck.applyTheme("Basic White", { layouts: { Statement: "Nope" } }), /no "Nope" layout/);
});

test("fromMarkdown in another theme", async () => {
  const deck = await fromMarkdown("# One\n\n- a\n- b\n", { theme: otherTheme("Basic White") });
  assert.equal((await reopen(deck)).slides[0].body, "a\nb");
});
