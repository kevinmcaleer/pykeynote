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
npm install keynotejs
```

It needs Node 20.12 or later and ships ES modules with TypeScript types.
From CommonJS, use `require("keynotejs")` on Node 22, or `await import("keynotejs")`.

## Reading a deck

```ts
import { Presentation } from "keynotejs";

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
import { Presentation, fromMarkdown } from "keynotejs";
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

## Markdown

`toMarkdown()` writes one block per slide, separated by `---`. Slide
settings go in HTML comments, and presenter notes follow a `???` line:

```markdown
<!-- layout: Title & Bullets -->
<!-- transition: dissolve 1.5s -->
# Why robots?

- They're fun
  - Mostly
- They're useful

???
Keep this one short.
```

## Development

The template decks and test fixtures are shared with the Python package, in
`../src/pykeynote/templates` and `../tests/fixtures`.

```sh
npm install
npm test
```

`src/schema.json` is generated from keynote-parser by
`python scripts/dump_schema.py`.
