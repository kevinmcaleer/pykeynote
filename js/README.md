# keynotejs

Create, read and edit Apple Keynote presentations from JavaScript and
TypeScript. keynotejs works on `.key` files directly, so it runs anywhere
Node does. You don't need Keynote or a Mac.

It is the JavaScript port of [pykeynote](https://pypi.org/project/pykeynote/)
and does the same things with the same files: a deck written by one reads
the same in the other.

A `.key` file is a zip of Snappy-compressed protobuf archives (`Index/*.iwa`)
plus images and media in `Data/`. The message definitions come from
[keynote-parser](https://github.com/psobot/keynote-parser) and cover files
saved by Keynote up to 14.5.

## Install

```sh
npm install @kevsmac/keynotejs
```

It needs Node 20.12 or later, or a modern browser (see
[In the browser](#in-the-browser)), and ships ES modules with TypeScript
types. From CommonJS, use `require("@kevsmac/keynotejs")` on Node 22, or
`await import("@kevsmac/keynotejs")`.

## Reading a deck

```ts
import { Presentation } from "@kevsmac/keynotejs";

const deck = await Presentation.open("talk.key");
console.log(deck.theme, deck.size, deck.layouts);

for (const slide of deck) {
  console.log(slide.index, slide.layout, slide.title);
  for (const para of slide.paragraphs) {     // text, indent level, bulleted?
    console.log("  ".repeat(para.level), para.text);
  }
  console.log(slide.notes, slide.transition.effect, slide.skipped);
}

console.log(deck.toMarkdown());
```

`title` and `body` are `null` when the slide's layout hides that placeholder.

## Making and changing decks

```ts
import { Presentation, fromMarkdown } from "@kevsmac/keynotejs";
import { readFile } from "node:fs/promises";

const deck = await Presentation.create();       // Basic White, 16:9, no slides yet
// Presentation.create({ aspect: "4:3" }) gives Keynote's Standard 1024 x 768 size
deck.addSlide("Title", { title: "Robots!", body: "Kevin McAleer" });
const slide = deck.addSlide("Title & Bullets", {
  title: "Why robots?",
  body: [{ text: "They're fun" }, { text: "Mostly", level: 1 }, "They're useful"],
  notes: "Keep this one short.",
});
slide.setTransition("dissolve", { duration: 1.5 });
await deck.save("talk.key");

const again = await Presentation.open("talk.key");
again.slide(1).title = "Why robots? 🤖";
again.duplicateSlide(1);
again.moveSlide(2, 0);
again.deleteSlide(-1);
again.slide(0).skipped = true;
await again.save();                              // back to talk.key

const fromMd = await fromMarkdown(await readFile("talk.md", "utf8"));
await fromMd.save("from-markdown.key");
```

`addSlide` copies a slide that already uses the layout, so it keeps the
theme's look. A deck from `Presentation.create()` has one of every layout to
copy from, kept out of sight and left out when you save. For a deck you
opened, at least one slide must already use the layout.

Without the file system, use `Presentation.fromBytes(bytes)` and
`deck.toBytes()`.

### Builds, transitions and subtitles

```ts
const s = deck.addSlide("Title & Bullets", { title: "test", body: ["some text", "more points", "last bits"] });
s.addSubtitle("sub title");                     // in the theme's Subtitle style, under the title
s.setTransition("wipe", { duration: 0.75 });     // direction: "from right" and so on
s.addBuild("title", { effect: "wipe", direction: "from left" });
s.addBuild("subtitle", { effect: "wipe", direction: "from left", start: "after previous", delay: 0.1 });
s.addBuild("body", { effect: "fade and move", delivery: "by bullet", duration: 0.3 });

// or one look for every slide, leaving out builds a slide has no text for:
deck.applyStyle({
  transition: { effect: "wipe", duration: 0.75 },
  titleBuild: { effect: "wipe", direction: "from left" },
  subtitleBuild: { effect: "wipe", start: "after previous", delay: 0.1 },
  bodyBuild: { effect: "fade and move", delivery: "by bullet", duration: 0.3 },
});
```

`start` is `"on click"`, `"after previous"` or `"with previous"`, and `delay`
is the seconds a build's first step waits; as in Keynote, every bullet of a
build starts the way `start` says.
`direction` is `"from left"`, `"from right"`, `"from top"` or `"from
bottom"`, for effects that move. Each build in `slide.builds` reports
`start`, `delay` and `direction`, and `slide.subtitle` reads or sets the
subtitle. On the "Title" layouts the subtitle is the body placeholder
("Presentation Subtitle"), which `addSubtitle` fills.

## Images, shapes, tables and charts

```ts
const slide = deck.addSlide("Blank");

// PNG, JPEG or GIF bytes. A free photo placeholder takes the image;
// otherwise it goes on top, centred unless you give a position.
slide.addImage(await readFile("robot.png"), {
  position: [100, 80], size: [640, null],         // null keeps the picture's shape
  description: "A robot", name: "robot.png",
});

const star = slide.addShape("star", { x: 900, y: 100, width: 300, height: 300, text: "New!", fill: "#3366ff" });
slide.addTextBox("Free text", { x: 100, y: 900, width: 600, height: 80 });

slide.addTable([["Name", "Score"], ["Ada", 42], ["Bob", 3.5]], { headerRows: 1 });
slide.addChart("column", [[1, 2, 3], [4, 5, 6]], ["2024", "2025"], ["Q1", "Q2", "Q3"],
  { x: 60, y: 60, width: 900, height: 500 });

slide.addBuild("title", "dissolve");
slide.addBuild(star, { effect: "move in", duration: 0.5 });
```

Everything has a sensible default position and size, centred on the slide.
`slide.images`, `shapes`, `tables`, `charts`, `drawables` and `builds`
read them back, from your decks and Keynote's alike, and each can be edited:
`table.setCell(1, 1, 43)`, `table.setRows(rows)`, `chart.setData(...)`,
`chart.chartType = "bar"`, `shape.text`, `shape.fill`, `shape.position`,
`shape.size`, `slide.replaceImage(...)`, `slide.deleteDrawable(...)` and
`slide.clearBuilds()`. `SHAPE_KINDS` and `CHART_TYPES` list the kinds you can
add. Duplicating a slide gives it its own copies of its tables and charts.

Tables and charts are copied from a deck bundled with the package, which
`Presentation.create()` and `open()` load for you. With `fromBytes`, call
`await preload()` once first.

## Themes

`themes()` lists the bundled themes, each at 16:9 and 4:3. They are
Basic White, Basic Black, Basic Color, Classic White, Color Gradient,
Minimalist Light, Minimalist Dark and Briefing (Keynote spells two of them
"Colour"; use the US spelling here). Start a deck in
one, or switch an existing deck to another:

```ts
import { Presentation, themes } from "@kevsmac/keynotejs";

console.log(themes());                           // ["Basic Black", "Basic White", ...]
const dark = await Presentation.create({ theme: "Basic Black", aspect: "4:3" });

const talk = await Presentation.open("talk.key");
await talk.applyTheme("Basic Black", { layouts: { Quote: "Statement" } });
await talk.save("talk-dark.key");
```

`applyTheme` rebuilds each slide on the new theme's layout of the same
name, or the closest one that shows a title and body where the slide has
them (see `matchLayout`). Titles and bodies with their indent levels,
subtitles, notes, transitions, skipping and builds on titles, subtitles and
bodies come along. Images,
shapes, text boxes, tables, charts and text formatting beyond the layout's
own don't.

## Markdown

`toMarkdown()` writes one block per slide, separated by `---`. Slide
settings go in HTML comments, and presenter notes follow a `???` line:

```markdown
<!-- layout: Title & Bullets -->
<!-- transition: wipe 0.75s from left -->
<!-- build: subtitle, wipe, 1s, after previous, delay 0.1s -->
# Why robots?
## A subtitle

- They're fun
  - Mostly
- They're useful

???
Keep this one short.
```

Images are written as `![description](file "x,y wxh")` and tables as pipe
tables, so a deck survives the trip both ways. Builds are
`<!-- build: body, dissolve, by bullet, 1s -->` comments, which can also
take a start, `delay 0.1s` and a direction, and a `##` line under the title
is its subtitle. Pass
`{ imageDir: "images", onImage: (path, data) => ... }` to `toMarkdown` to save
the pictures, and `{ baseDir }` or `{ images: async (path) => bytes }` to
`fromMarkdown` to find them again.

## In the browser

keynotejs has no Node-only imports at the top level, so bundlers such as
Vite and esbuild take it as it is. Read and write bytes instead of files:

```ts
import { Presentation, preload } from "@kevsmac/keynotejs";

const deck = await Presentation.create();        // fetches the bundled theme
deck.addSlide("Title", { title: "Made in a browser" });
const blob = new Blob([deck.toBytes()], { type: "application/x-iwork-keynote-sffkey" });

await preload();                                 // before adding tables or charts to a fromBytes deck
const opened = Presentation.fromBytes(new Uint8Array(await file.arrayBuffer()));
```

The bundled decks in `templates/` are fetched relative to the module. If
your bundler moves them, serve that folder yourself and point keynotejs at it,
or pass a theme deck's bytes directly:

```ts
import { setTemplateLoader } from "@kevsmac/keynotejs";

setTemplateLoader(async (file) => new Uint8Array(await (await fetch(`/keynote/${file}`)).arrayBuffer()));
const deck = await Presentation.create({ template: myThemeBytes });
```

`open`, `save` and Markdown image files need Node.

## Development

The template decks and test fixtures are shared with the Python package, in
`../src/pykeynote/templates` and `../tests/fixtures`.

```sh
npm install
npm test
node scripts/cross-check.mjs     # against pykeynote: pip install -e .. first
```

The cross check has both libraries build the same deck and read each other's
files back. CI runs it on every pull request.

`src/schema.json` is generated from keynote-parser by
`python scripts/dump_schema.py`.
