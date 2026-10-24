// Checks keynotejs against pykeynote, both ways.
//
// Both libraries build the same deck (see scenario() here and in cross_check.py).
// Each one opens the other's file and must see what its author saw, and both
// must have built the same deck. Run after `npm run build`, with pykeynote
// importable by $PYTHON (default python3):
//
//     node scripts/cross-check.mjs
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { Presentation } from "../dist/index.js";
import { png } from "../dist/test/helpers.js";

const here = fileURLToPath(new URL(".", import.meta.url));

async function scenario(picture) {
  const deck = await Presentation.create({ theme: "Basic White", aspect: "16:9" });
  const intro = deck.addSlide("Title & Bullets", { title: "Cross check", body: "Written by one library\nRead by the other\n\nThird point" });
  intro.notes = "Speaker notes";
  intro.addBuild("title", { effect: "move in", duration: 0.5 });
  intro.addBuild("body", "dissolve");

  const shapes = deck.addSlide("Blank");
  const star = shapes.addShape("star", { x: 100, y: 120, width: 300, height: 300, text: "Star", fill: "#3366ff" });
  shapes.addShape("rounded rectangle", { x: 500, y: 120, width: 400, height: 200, style: 2 });
  shapes.addTextBox("Free text", { x: 100, y: 600, width: 600, height: 80 });
  shapes.addBuild(star, { effect: "dissolve" });

  const table = deck.addSlide("Title Only", { title: "Scores" });
  table.addTable([["Name", "Score", "Pass"], ["Ada", 42, true], ["Bob", 3.5, false], ["Cy", -7, null]], { headerColumns: 1 });

  const charts = deck.addSlide("Blank");
  charts.addChart("column", [[1, 2, 3], [4, 5, null]], ["2024", "2025"], ["Q1", "Q2", "Q3"], { x: 60, y: 60, width: 900, height: 500 });
  charts.addChart("pie", [[3, 5, 2]], ["Share"], ["a", "b", "c"], { x: 1000, y: 60, width: 800, height: 600 });

  const photo = deck.addSlide("Blank");
  photo.addImage(picture, { position: [200, 100], size: [640, null], description: "A red square", name: "red.png" });

  const style = deck.addSlide("Title & Bullets", { title: "Style", body: ["one", "two", "three"] });
  style.addSubtitle("sub title");
  style.setTransition("wipe", { duration: 0.75, direction: "from right" });
  style.addBuild("title", { effect: "wipe", direction: "from left" });
  style.addBuild("subtitle", { effect: "wipe", direction: "from top", start: "after previous", delay: 0.1 });
  style.addBuild("body", { effect: "fade and move", delivery: "by bullet", duration: 0.3 });

  const skipped = deck.addSlide("Title Only", { title: "Skipped" });
  skipped.skipped = true;
  return deck;
}

/** What a deck holds, without identifiers that differ from one build to the next. */
function view(deck) {
  return deck.slides.map((slide) => {
    const drawables = slide.drawables;
    const target = (t) => (typeof t === "number" ? `drawable ${drawables.findIndex((d) => d.identifier === t)}` : t);
    return {
      ...slide.toJSON(),
      builds: slide.builds.map((b) => ({ target: target(b.target), kind: b.kind, effect: b.effect, delivery: b.delivery, duration: b.duration, steps: b.steps, start: b.start, delay: b.delay, direction: b.direction })),
    };
  });
}

/** camelCase keys to snake_case, as pykeynote names them. */
function snake(value) {
  if (Array.isArray(value)) return value.map(snake);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k.replace(/[A-Z]/g, (c) => "_" + c.toLowerCase()), snake(v)]));
  }
  return value;
}

/** Positions and sizes are floats; compare them to a thousandth of a point. */
function rounded(value) {
  if (Array.isArray(value)) return value.map(rounded);
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, rounded(v)]));
  return typeof value === "number" ? Math.round(value * 1000) / 1000 : value;
}

const dir = mkdtempSync(join(tmpdir(), "keynote-cross-"));
const picture = png(64, 64, [200, 30, 30]);
writeFileSync(join(dir, "red.png"), picture);

const ours = await scenario(picture);
await ours.save(join(dir, "js.key"));
const markdown = ours.toMarkdown();
writeFileSync(join(dir, "js.json"), JSON.stringify({ slides: snake(view(ours)), markdown }, null, 1));

const python = process.env.PYTHON ?? "python3";
const run = spawnSync(python, [join(here, "cross_check.py"), dir], { stdio: "inherit" });
if (run.error) throw run.error;
if (run.status !== 0) process.exit(run.status ?? 1);

// pykeynote's deck, as pykeynote saw it, must be what keynotejs sees.
const theirs = JSON.parse(readFileSync(join(dir, "py.json"), "utf8"));
const opened = await Presentation.open(join(dir, "py.key"));
assert.deepEqual(rounded(snake(view(opened))), rounded(theirs.slides), "keynotejs reads pykeynote's deck differently");
assert.equal(opened.toMarkdown(), theirs.markdown);

// And the two libraries built the same deck.
assert.deepEqual(rounded(theirs.slides), rounded(snake(view(ours))), "the libraries built different decks");
assert.equal(theirs.markdown, markdown);

// Edits made by one library survive the other: change pykeynote's deck and let it read it back.
opened.slide(2).tables[0].setCell(1, 1, 43);
opened.slide(3).charts[0].setData([[9, 8]], ["Only"], ["P", "Q"]);
opened.slide(1).shapes[0].text = "Edited";
await opened.save(join(dir, "js-edited.key"));
const check = spawnSync(python, [join(here, "cross_check.py"), dir, "--edited"], { stdio: "inherit" });
if (check.status !== 0) process.exit(check.status ?? 1);

console.log(`keynotejs and pykeynote agree (files in ${dir})`);
