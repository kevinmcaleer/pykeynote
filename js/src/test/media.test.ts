import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import assert from "node:assert/strict";

import { Presentation, fromMarkdown, imageFormat, parseMarkdown, themes } from "../index.js";
import { checkConsistent, checkData, fixture, jpegHeader, png, reopen, tmpPath } from "./helpers.js";

const close = (a: number, b: number) => Math.abs(a - b) < 1e-6;

test("image format", () => {
  assert.deepEqual(imageFormat(png(30, 20)), ["png", 30, 20]);
  assert.deepEqual(imageFormat(jpegHeader(640, 480)), ["jpeg", 640, 480]);
  const gif = new Uint8Array(18);
  gif.set(new TextEncoder().encode("GIF89a"));
  gif.set([7, 0, 9, 0], 6);
  assert.deepEqual(imageFormat(gif), ["gif", 7, 9]);
  assert.throws(() => imageFormat(new TextEncoder().encode("not an image at all")), /PNG, JPEG and GIF/);
});

test("read a placeholder's sample photo", async () => {
  const deck = await fixture("layouts-basic-white.key");
  const photo = deck.slides.find((s) => s.layout === "Photo")!;
  const [image] = photo.images;
  assert.equal(image.placeholder, "Media");
  assert.ok(image.isSample);
  assert.equal(image.filename, null);
  assert.deepEqual([image.position, image.size], [[0, 0], [1024, 768]]);
  assert.ok(image.description);
});

test("a new picture drops the sample photo's description", async () => {
  // Keynote shows the sample photo's caption as the new picture's description otherwise.
  const slide = (await Presentation.create()).addSlide("Title & Photo", { title: "Robots" });
  assert.ok(slide.placeholders[0].description);
  const image = slide.addImage(png(20, 10));
  assert.equal(image.description, "");
  assert.equal(slide.replaceImage(image, png(10, 10)).description, "");
});

test("fill a placeholder", async () => {
  const deck = await Presentation.create();
  const slide = deck.addSlide("Title & Photo", { title: "Robots" });
  const before = slide.placeholders[0];
  const added = slide.addImage(png(1600, 900), { description: "A red square" });
  assert.equal(added.identifier, before.identifier);
  assert.deepEqual([added.position, added.size], [before.position, before.size]);

  const again = await reopen(deck);
  const [image] = again.slide(0).images;
  assert.equal(image.placeholder, "Media");
  assert.ok(!image.isSample);
  assert.deepEqual(image.pixelSize, [1600, 900]);
  assert.equal(image.description, "A red square");
  assert.deepEqual(image.data, png(1600, 900));
  assert.deepEqual([image.position, image.size], [before.position, before.size]);
  // The picture itself covers the crop, keeping its shape.
  const obj = again.package.get(image.identifier);
  const g = obj.super.geometry;
  assert.ok(close(g.size.width / g.size.height, 16 / 9));
  assert.ok(g.size.width >= image.size[0] - 0.01 && g.size.height >= image.size[1] - 0.01);
  assert.ok(!("thumbnailData" in obj && Object.hasOwn(obj, "thumbnailData")));
  checkConsistent(again);
  checkData(again);
});

test("add free images", async () => {
  const deck = await Presentation.create();
  const slide = deck.addSlide("Blank");
  const centred = slide.addImage(png(400, 300));
  const placed = slide.addImage(png(800, 800, [0, 0, 200]), { position: [100, 50], size: [200, null], description: "Blue" });
  assert.deepEqual([centred.position, centred.size], [[760, 390], [400, 300]]);
  assert.deepEqual(placed.size, [200, 200]);
  const big = slide.addImage(png(4000, 1000), { placeholder: false });
  assert.ok(close(big.size[0], 1536) && close(big.size[1], 384)); // fits in 80% of the slide

  const again = await reopen(deck);
  const images = again.slide(0).images;
  assert.deepEqual(images.slice(0, 2).map((i) => i.size), [[400, 300], [200, 200]]);
  assert.deepEqual([images[1].position, images[1].description], [[100, 50], "Blue"]);
  assert.ok(images.every((i) => i.placeholder === null));
  checkConsistent(again);
  checkData(again);
});

test("the same picture is stored once", async () => {
  const deck = await Presentation.create();
  const slide = deck.addSlide("Blank");
  slide.addImage(png(10, 10), { name: "a.png" });
  slide.addImage(png(10, 10), { name: "b.png" });
  const again = await reopen(deck);
  const [a, b] = again.slide(0).images;
  assert.equal(a.filename, `a-${again.package.get(a.identifier).data.identifier}.png`);
  assert.equal(b.filename, a.filename);
});

test("file names come from the name given", async () => {
  const deck = await Presentation.create();
  const image = deck.addSlide("Blank").addImage(png(50, 40), { name: "my photo.png" });
  assert.match(image.filename!, /^my-photo-\d+\.png$/);
});

test("replace and remove images", async () => {
  const deck = await Presentation.create();
  const slide = deck.addSlide("Photo - 3 Up");
  assert.deepEqual(slide.placeholders.map((i) => i.placeholder), ["Media", "Media-1", "Media-2"]);
  slide.addImage(png(100, 100));
  slide.addImage(png(100, 100, [0, 200, 0]), { placeholder: "Media-2" });
  assert.deepEqual(slide.placeholders.map((i) => i.isSample), [false, true, false]);
  slide.removeImage("Media-1");
  const free = slide.addImage(png(300, 100), { position: [0, 0], size: [300, 100] });
  slide.addBuild(free.identifier, "dissolve");

  const again = await reopen(deck);
  const s = again.slide(0);
  assert.deepEqual(s.images.map((i) => i.placeholder), ["Media-2", "Media", null]); // back to front
  s.replaceImage(-1, png(100, 100, [9, 9, 9]));
  const replaced = s.images[s.images.length - 1];
  assert.deepEqual([replaced.size, replaced.position], [[100, 100], [100, 0]]); // fits in the old frame
  const oldFile = s.images[1].filename;
  s.removeImage("Media");
  s.removeImage(replaced);
  assert.deepEqual(s.builds, []);

  const final = await reopen(again, "final.key");
  assert.deepEqual(final.slide(0).images.map((i) => i.placeholder), ["Media-2"]);
  assert.ok(!final.package.filenames.includes("Data/" + oldFile));
  assert.ok(!final.slide(0).slide.sage_tag_to_info_map.some((e: { tag: string }) => e.tag === "Media"));
  checkConsistent(final);
  checkData(final);
});

test("image errors", async () => {
  const deck = await Presentation.create();
  const slide = deck.addSlide("Blank");
  assert.throws(() => slide.addImage(png(10, 10), { placeholder: true }), /no empty media placeholder/);
  assert.throws(() => slide.removeImage(0), /no image/);
  assert.throws(() => slide.replaceImage("Media", png(10, 10)), /no media placeholder/);
});

test("images on an opened deck", async () => {
  const deck = await fixture("builds-talk.key");
  deck.slide(1).addImage(png(64, 64), { position: [10, 10] });
  const again = await reopen(deck);
  const images = again.slide(1).images;
  assert.deepEqual(images[images.length - 1].size, [64, 64]);
  checkConsistent(again);
  checkData(again);
});

const MARKDOWN = `# Robots

![A red robot](red.png)

---

# Parts

- Motors
- Sensors

![Wiring](parts/wiring.png)
![Logo](red.png "1700,40 160x90")

---

![One](red.png)
![Two](parts/wiring.png)
`;

function writePictures(): string {
  const dir = dirname(tmpPath());
  mkdirSync(join(dir, "parts"));
  writeFileSync(join(dir, "red.png"), png(160, 90));
  writeFileSync(join(dir, "parts", "wiring.png"), png(90, 160, [0, 0, 255]));
  return dir;
}

test("images in Markdown", async () => {
  const dir = writePictures();
  const specs = parseMarkdown(MARKDOWN);
  assert.deepEqual(specs[1].images.map((i) => i.path), ["parts/wiring.png", "red.png"]);
  assert.deepEqual([specs[1].images[1].position, specs[1].images[1].size], [[1700, 40], [160, 90]]);

  const deck = await fromMarkdown(MARKDOWN, { baseDir: dir });
  assert.deepEqual(deck.slides.map((s) => s.layout), ["Title & Photo", "Title, Bullets & Photo", "Photo - 3 Up"]);
  // The unused third placeholder is removed rather than showing a sample photo.
  assert.deepEqual(deck.slides.map((s) => s.images.length), [1, 2, 2]);
  assert.ok(!deck.slides.some((s) => s.images.some((i) => i.isSample)));

  const again = await reopen(deck);
  const out = join(dir, "out");
  mkdirSync(out);
  const md = again.toMarkdown({ imageDir: out, onImage: (path, data) => writeFileSync(path, data) });
  assert.equal(again.slide(0).images[0].name, "red.png");
  assert.ok(md.includes(`![A red robot](${join(out, "red.png").replaceAll("\\", "/")})`));
  assert.deepEqual(new Uint8Array(readFileSync(join(out, "red.png"))), png(160, 90));
  assert.ok(md.includes('"1700,40 160x90")'));
  const rebuilt = await fromMarkdown(md);
  assert.equal(rebuilt.toMarkdown({ imageDir: out }), md);
  checkConsistent(again);
});

test("images in Markdown from an images function, as in a browser", async () => {
  const files: Record<string, Uint8Array> = { "red.png": png(160, 90), "parts/wiring.png": png(90, 160, [0, 0, 255]) };
  const deck = await fromMarkdown(MARKDOWN, { images: (path) => files[path] });
  assert.deepEqual(deck.slides.map((s) => s.images.length), [1, 2, 2]);
});

test("Markdown without an image folder, and escaping", async () => {
  const deck = await Presentation.create();
  const slide = deck.addSlide("Title & Photo", { title: "T" });
  slide.addImage(png(10, 10), { description: "a [b] c", name: "pic.png" });
  const md = deck.toMarkdown();
  assert.ok(md.includes("![a [b\\] c](pic.png)"));
  assert.equal(parseMarkdown(md)[0].images[0].description, "a [b] c");
  const statement = await Presentation.create();
  statement.addSlide("Statement", { body: "![not an image](x.png)" });
  assert.deepEqual(parseMarkdown(statement.toMarkdown())[0].images, []);
});

test("Markdown images in every theme", async () => {
  const dir = writePictures();
  for (const theme of themes()) {
    const deck = await fromMarkdown(MARKDOWN, { theme, baseDir: dir });
    assert.deepEqual(deck.slides.map((s) => s.images.length), [1, 2, 2], theme);
    assert.ok(!deck.slides.some((s) => s.images.some((i) => i.isSample)));
    checkConsistent(await reopen(deck));
  }
});
