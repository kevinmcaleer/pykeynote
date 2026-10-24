/**
 * Convert between presentations and Markdown.
 *
 * Each slide becomes a block, and blocks are separated by ``---``:
 *
 *     <!-- layout: Title & Bullets -->
 *     <!-- transition: wipe 0.75s from left -->
 *     <!-- build: title, wipe, all at once, 1s, from left -->
 *     <!-- build: subtitle, wipe, all at once, 1s, after previous, delay 0.1s, from left -->
 *     <!-- build: body, fade and move, by bullet, 0.3s -->
 *     # Slide title
 *     ## A subtitle
 *
 *     - A bullet
 *       - An indented bullet
 *
 *     A paragraph without a bullet
 *
 *     | Name | Score |
 *     | --- | --- |
 *     | Ada | 42 |
 *     ![A robot arm](images/arm.png)
 *     ![Logo](images/logo.png "1600,40 200x100")
 *
 *     ???
 *     Presenter notes
 *
 * Tables are pipe tables; a ``| --- |`` line ends the header rows. Slide
 * settings go in HTML comments, so the Markdown still renders cleanly
 * elsewhere. Notes follow a line holding only ``???``, as in remark.js.
 * A ``##`` heading straight after the ``#`` title is the slide's subtitle.
 *
 * A build comment holds a target (title, subtitle or body), an effect, then
 * in any order: a delivery ("all at once" or "by bullet"), a duration
 * ("1s"), "in" or "out", a start ("on click", "after previous" or "with
 * previous"), a delay ("delay 0.1s") and a direction ("from left", "from
 * right", "from top" or "from bottom").
 *
 * An image fills the layout's next media placeholder, or, if its title gives
 * a frame (``"x,y"`` or ``"x,y widthxheight"``, in points), goes exactly there.
 */

import { STARTS, directionName, directionValue, type BuildOptions, type Start } from "./builds.js";
import { Presentation, type Aspect, type Slide } from "./document.js";
import type { CellValue } from "./tables.js";
import type { Paragraph } from "./text.js";

const SLIDE_SEPARATOR = "---";
const NOTES_MARKER = "???";

// A plain paragraph starting like this would read as Markdown syntax.
const NEEDS_ESCAPE = /^(#|[-*+] |\d+[.)] |>|---|\?\?\?|<!--|!\[)/;

/** Format like Python's ``f"{value:g}"``: 1.5 is "1.5", 1.0 is "1". */
function fmtG(value: number): string {
  return String(Number(value.toPrecision(6)));
}

function fmtSeconds(value: number): string {
  return `${fmtG(value)}s`;
}

function fmtNumber(value: number): string {
  return fmtG(Math.round(value * 10) / 10);
}

export interface ToMarkdownOptions {
  /** A folder to link images from, e.g. ``"images"`` gives ``![...](images/robot.png)``. */
  imageDir?: string;
  /** Called with each image's link path and bytes, so you can save it there. */
  onImage?: (path: string, data: Uint8Array) => void;
}

/** Each name images were added under, with the files stored under it. */
function imageNames(presentation: Presentation): Map<string, Set<string>> {
  const names = new Map<string, Set<string>>();
  for (const slide of presentation.slides) {
    for (const image of slide.images) {
      if (!image.name) continue;
      if (!names.has(image.name)) names.set(image.name, new Set());
      names.get(image.name)!.add(image.filename!);
    }
  }
  return names;
}

function imageLines(slide: Slide, options: ToMarkdownOptions, names: Map<string, Set<string>>): string[] {
  const lines: string[] = [];
  const placeholders = slide.placeholders.filter((i) => !i.isSample);
  const free = slide.images.filter((i) => i.placeholder === null && !i.isSample);
  for (const image of [...placeholders, ...free]) {
    // The name it was added under, unless another picture in the deck has it too.
    const files = names.get(image.name!);
    let path = files === undefined || (files.size === 1 && files.has(image.filename!)) ? image.name! : image.filename!;
    if (options.imageDir !== undefined) path = options.imageDir.replaceAll("\\", "/").replace(/\/+$/, "") + "/" + path;
    options.onImage?.(path, image.data!);
    if (path.includes(" ") || path.includes(")")) path = `<${path}>`;
    const alt = image.description.trim().split(/\s+/).filter(Boolean).join(" ").replaceAll("]", "\\]");
    let frame = "";
    if (image.placeholder === null) {
      const [x, y] = image.position;
      const [w, h] = image.size;
      frame = ` "${fmtNumber(x)},${fmtNumber(y)} ${fmtNumber(w)}x${fmtNumber(h)}"`;
    }
    lines.push(`![${alt}](${path}${frame})`);
  }
  return lines;
}

export function slideToMarkdown(slide: Slide, options: ToMarkdownOptions = {}, names?: Map<string, Set<string>>): string {
  const lines: string[] = [`<!-- layout: ${slide.layout} -->`];
  const t = slide.transition;
  if (t.effect) lines.push(`<!-- transition: ${t.effect} ${fmtSeconds(t.duration)}${t.direction ? " " + t.direction : ""} -->`);
  if (slide.skipped) lines.push("<!-- skipped -->");
  for (const b of slide.builds) {
    if (typeof b.target !== "string") continue;
    const parts = [b.target, b.effect, b.delivery === "By Paragraph" ? "by bullet" : b.delivery.toLowerCase(), fmtSeconds(b.duration)];
    if (b.kind !== "in") parts.push(b.kind);
    if (b.start !== "on click") parts.push(b.start);
    if (b.delay) parts.push(`delay ${fmtSeconds(b.delay)}`);
    if (b.direction) parts.push(b.direction);
    lines.push(`<!-- build: ${parts.join(", ")} -->`);
  }

  const title = slide.title;
  let subtitleIsBody = false;
  if (title !== null && title.trim()) {
    lines.push("# " + title.trim().split(/\s+/).join(" "));
    let subtitle = slide.subtitle;
    const filled = slide.paragraphs.filter((p) => p.text.trim());
    // a body subtitle of several lines stays body text
    if (subtitle !== null && slide.bodyIsSubtitle() && (filled.length !== 1 || subtitle.includes("\n"))) subtitle = null;
    if (subtitle !== null) {
      lines.push("## " + subtitle.trim().split(/\s+/).join(" "));
      subtitleIsBody = slide.bodyIsSubtitle();
    }
  }

  const body: string[] = [];
  for (const para of subtitleIsBody ? [] : slide.paragraphs) {
    const text = para.text.replaceAll("\n", "<br>").trim();
    if (!text) continue;
    if (para.bulleted) {
      body.push("  ".repeat(para.level) + "- " + text);
    } else {
      if (body.length) body.push("");
      body.push(NEEDS_ESCAPE.test(text) ? "\\" + text : text);
    }
  }
  if (body.length) lines.push("", ...body);

  for (const table of slide.tables) lines.push("", ...tableToMarkdown(table.rows, table.headerRows));
  const images = imageLines(slide, options, names ?? imageNames(slide.presentation));
  if (images.length) lines.push("", ...images);

  const notes = slide.notes.trim();
  if (notes) lines.push("", NOTES_MARKER, notes);
  return lines.join("\n") + "\n";
}

function cellText(value: CellValue): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "boolean") return value ? "TRUE" : "FALSE";
  if (typeof value === "number") return Math.abs(value) < 1e15 ? fmtG(value) : String(value);
  if (value instanceof Date) return value.toISOString().replace(/\.000Z$/, "").replace(/Z$/, "");
  return String(value).replaceAll("|", "\\|").replaceAll("\n", "<br>");
}

/** A pipe table, one line per row. Header rows go above the ``---`` line; with none, it goes first. */
export function tableToMarkdown(rows: CellValue[][], headerRows = 1): string[] {
  const out: string[] = [];
  const width = Math.max(...rows.map((r) => r.length));
  const separator = "| " + new Array(width).fill("---").join(" | ") + " |";
  if (headerRows === 0) out.push("| " + new Array(width).fill("").join(" | ") + " |", separator);
  rows.forEach((row, i) => {
    out.push("| " + row.map(cellText).join(" | ") + " |");
    if (i + 1 === headerRows) out.push(separator);
  });
  return out;
}

/** The presentation as Markdown. */
export function toMarkdown(presentation: Presentation, options: ToMarkdownOptions = {}): string {
  const names = imageNames(presentation);
  return presentation.slides.map((s) => slideToMarkdown(s, options, names)).join(`\n${SLIDE_SEPARATOR}\n\n`);
}

// --- Markdown to a presentation -------------------------------------------------

const COMMENT = /^<!--\s*(.*?)\s*-->$/;
const HEADING = /^#{1,2}\s+(.*)$/;
const BULLET = /^(\s*)(?:[-*+]|\d+[.)])\s+(.*)$/;
const TRANSITION = /^(.*?)(?:\s+([\d.]+)\s*s)?(?:\s+((?:from|left|right|top|bottom)\b.*))?$/;
const IMAGE = /^!\[((?:\\.|[^\]])*)\]\(\s*(<[^>]*>|[^\s)]+)(?:\s+"([^"]*)")?\s*\)$/;
const FRAME = /^\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)(?:\s+([\d.]+)\s*[x×]\s*([\d.]+))?\s*$/;
const TABLE_ROW = /^\s*\|.*\|\s*$/;
const TABLE_SEPARATOR = /^\s*\|(\s*:?-{3,}:?\s*\|)+\s*$/;

/** An image parsed from Markdown. ``position`` and ``size`` are set when its title gives a frame. */
export interface ImageSpec {
  path: string;
  description: string;
  position: [number, number] | null;
  size: [number, number] | null;
}

export interface TableSpec {
  rows: CellValue[][];
  headerRows: number;
}

/** One slide parsed from Markdown, before it is added to a deck. */
export interface SlideSpec {
  layout: string | null;
  title: string | null;
  subtitle: string | null;
  paragraphs: Required<Paragraph>[];
  notes: string;
  transition: string | null;
  transitionDuration: number | null;
  transitionDirection: string | null;
  skipped: boolean;
  builds: (BuildOptions & { target: string })[];
  tables: TableSpec[];
  images: ImageSpec[];
}

/** The layout a slide gets when its Markdown doesn't name one. */
export function defaultLayout(spec: SlideSpec): string {
  const bulleted = spec.paragraphs.some((p) => p.bulleted);
  const photos = (spec.images ?? []).filter((i) => i.position === null).length;
  if (photos) {
    if (spec.paragraphs.length) return "Title, Bullets & Photo";
    if (spec.title) return "Title & Photo";
    return photos === 1 ? "Photo" : "Photo - 3 Up";
  }
  if (spec.tables?.length && !spec.paragraphs.length) return spec.title ? "Title Only" : "Blank";
  if (spec.title && spec.subtitle !== null && !spec.paragraphs.length) return "Title"; // a title card: its body is the subtitle
  if (spec.title && spec.paragraphs.length) return bulleted ? "Title & Bullets" : "Title";
  if (spec.title) return "Title Only";
  if (spec.paragraphs.length) return bulleted ? "Bullets" : "Statement";
  return "Blank";
}

function splitRow(line: string): string[] {
  const inner = line.trim().slice(1, -1);
  return inner.split(/(?<!\\)\|/).map((c) => c.trim().replaceAll("\\|", "|"));
}

function cellValue(text: string): CellValue {
  text = text.replaceAll("<br>", "\n");
  if (text === "") return null;
  if (text === "TRUE" || text === "FALSE") return text === "TRUE";
  if (/^-?\d+$/.test(text)) return parseInt(text, 10);
  if (/^-?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?$/.test(text)) return parseFloat(text);
  return text;
}

function parseTable(lines: string[]): TableSpec {
  const rows: CellValue[][] = [];
  let headerRows = 0;
  for (const line of lines) {
    if (TABLE_SEPARATOR.test(line)) {
      headerRows = rows.length;
      continue;
    }
    rows.push(splitRow(line).map(cellValue));
  }
  if (headerRows === 1 && rows[0].every((v) => v === null)) {
    rows.shift(); // an empty header row stands for no header
    headerRows = 0;
  }
  const width = Math.max(...rows.map((r) => r.length));
  return { rows: rows.map((r) => [...r, ...new Array<CellValue>(width - r.length).fill(null)]), headerRows };
}

function clean(text: string): string {
  text = text.trim().replaceAll("<br>", "\n").replaceAll("<br/>", "\n").replaceAll("<br />", "\n");
  return text.startsWith("\\") ? text.slice(1) : text;
}

/** Read ``target, effect[, delivery][, 1.5s][, in|out][, start][, delay 0.1s][, direction]`` from a build comment. */
function parseBuild(value: string): BuildOptions & { target: string } {
  const parts = value.split(",").map((p) => p.trim()).filter(Boolean);
  if (parts.length < 2) throw new Error(`a build needs at least a target and an effect: ${JSON.stringify(value)}`);
  const build: BuildOptions & { target: string } = { target: parts[0].toLowerCase(), effect: parts[1] };
  for (const part of parts.slice(2)) {
    const low = part.toLowerCase().replaceAll("-", " ").split(/\s+/).join(" ");
    const delay = /^delay\s*([\d.]+)\s*s?$/.exec(low);
    if (/^[\d.]+\s*s$/.test(low)) build.duration = parseFloat(low);
    else if (delay) build.delay = parseFloat(delay[1]);
    else if (low === "in" || low === "out") build.kind = low;
    else if ((STARTS as readonly string[]).includes(low)) build.start = low as Start;
    else if (isDirection(low)) build.direction = directionName(directionValue(low)) ?? undefined;
    else build.delivery = low;
  }
  return build;
}

function isDirection(text: string): boolean {
  try {
    directionValue(text);
    return true;
  } catch {
    return false;
  }
}

function parseImage(match: RegExpExecArray): ImageSpec {
  let [, alt, path, title] = match;
  if (path.startsWith("<") && path.endsWith(">")) path = path.slice(1, -1);
  const image: ImageSpec = { path, description: alt.replace(/\\(.)/g, "$1"), position: null, size: null };
  const frame = FRAME.exec(title ?? "");
  if (frame) {
    image.position = [parseFloat(frame[1]), parseFloat(frame[2])];
    if (frame[3]) image.size = [parseFloat(frame[3]), parseFloat(frame[4])];
  }
  return image;
}

/** Width of leading whitespace, with tabs to the next multiple of 4. */
function indentWidth(ws: string): number {
  let col = 0;
  for (const ch of ws) col = ch === "\t" ? col + 4 - (col % 4) : col + 1;
  return col;
}

function splitLines(text: string): string[] {
  const lines = text.split(/\r\n|\r|\n/);
  if (lines.length && lines[lines.length - 1] === "") lines.pop();
  return lines;
}

/** Split Markdown in the {@link toMarkdown} format into slide specs. */
export function parseMarkdown(text: string): SlideSpec[] {
  const blocks: string[][] = [[]];
  let inFence = false;
  for (const line of splitLines(text)) {
    if (line.trim().startsWith("```")) inFence = !inFence;
    if (!inFence && line.trim() === SLIDE_SEPARATOR) blocks.push([]);
    else blocks[blocks.length - 1].push(line);
  }

  const specs: SlideSpec[] = [];
  for (const block of blocks) {
    if (!block.some((line) => line.trim())) continue;
    const spec: SlideSpec = {
      layout: null,
      title: null,
      subtitle: null,
      paragraphs: [],
      notes: "",
      transition: null,
      transitionDuration: null,
      transitionDirection: null,
      skipped: false,
      builds: [],
      tables: [],
      images: [],
    };
    let notes: string[] | null = null;
    const pending: string[] = []; // lines of a plain paragraph being collected
    const tableLines: string[] = [];

    const flush = () => {
      if (pending.length) {
        spec.paragraphs.push({ text: clean(pending.map((s) => s.trim()).join(" ")), level: 0, bulleted: false });
        pending.length = 0;
      }
      if (tableLines.length) {
        spec.tables.push(parseTable(tableLines));
        tableLines.length = 0;
      }
    };

    for (const line of block) {
      const stripped = line.trim();
      if (notes !== null) {
        notes.push(line);
        continue;
      }
      if (stripped === NOTES_MARKER) {
        flush();
        notes = [];
        continue;
      }
      const comment = COMMENT.exec(stripped);
      if (comment) {
        flush();
        const body = comment[1];
        const colon = body.indexOf(":");
        const key = (colon < 0 ? body : body.slice(0, colon)).trim().toLowerCase();
        const value = colon < 0 ? "" : body.slice(colon + 1).trim();
        if (key === "layout") {
          spec.layout = value;
        } else if (key === "transition") {
          const m = TRANSITION.exec(value)!;
          spec.transition = m[1].trim();
          spec.transitionDuration = m[2] ? parseFloat(m[2]) : null;
          spec.transitionDirection = m[3] ? m[3].trim() : null;
        } else if (key === "skipped") {
          spec.skipped = !["false", "no", "0"].includes(value.toLowerCase());
        } else if (key === "build") {
          spec.builds.push(parseBuild(value));
        }
        continue;
      }
      const image = IMAGE.exec(stripped);
      if (image) {
        flush();
        spec.images.push(parseImage(image));
        continue;
      }
      const heading = HEADING.exec(stripped);
      if (heading && spec.title === null && !spec.paragraphs.length && !pending.length) {
        spec.title = clean(heading[1]);
        continue;
      }
      if (heading && stripped.startsWith("## ") && spec.title !== null && spec.subtitle === null && !spec.paragraphs.length && !pending.length) {
        spec.subtitle = clean(heading[1]);
        continue;
      }
      if (TABLE_ROW.test(line) && !pending.length) {
        tableLines.push(line);
        continue;
      }
      if (tableLines.length) flush();
      const bullet = BULLET.exec(line);
      if (bullet) {
        flush();
        spec.paragraphs.push({ text: clean(bullet[2]), level: Math.floor(indentWidth(bullet[1]) / 2), bulleted: true });
        continue;
      }
      if (!stripped) {
        flush();
        continue;
      }
      pending.push(line);
    }
    flush();
    if (notes !== null) spec.notes = notes.join("\n").trim();
    specs.push(spec);
  }
  return specs;
}

export interface FromMarkdownOptions {
  theme?: string;
  aspect?: Aspect;
  /** The bundled theme deck's bytes, if you've loaded them yourself (see ``Presentation.create``). */
  template?: Uint8Array;
  /**
   * The bytes of the image at a path in the Markdown. By default, in Node,
   * paths are read from disk relative to ``baseDir``.
   */
  images?: (path: string) => Uint8Array | ArrayBuffer | Promise<Uint8Array | ArrayBuffer>;
  /** The folder image paths are relative to, in Node. Defaults to the current directory. */
  baseDir?: string;
}

async function readImageFile(path: string, baseDir?: string): Promise<Uint8Array> {
  if (/^[a-z]+:\/\//.test(path)) throw new Error(`can't add ${JSON.stringify(path)}: pass an images function to fetch it`);
  // Variables keep bundlers from trying to include Node's modules in browser builds.
  const fsName = "node:fs/promises";
  const pathName = "node:path";
  let fs: typeof import("node:fs/promises");
  let paths: typeof import("node:path");
  try {
    [fs, paths] = await Promise.all([import(/* @vite-ignore */ fsName), import(/* @vite-ignore */ pathName)]);
  } catch {
    throw new Error(`can't read ${JSON.stringify(path)} outside Node: pass an images function to fromMarkdown`);
  }
  return new Uint8Array(await fs.readFile(paths.resolve(baseDir ?? process.cwd(), path)));
}

/**
 * Build a new presentation from Markdown in the {@link toMarkdown} format.
 *
 * A slide without a ``layout`` comment gets one from its content: title and
 * bullets give "Title & Bullets", a title alone "Title Only", an image with
 * a title "Title & Photo", and so on. Media placeholders left without an
 * image are removed, rather than showing the theme's sample photos.
 */
export async function fromMarkdown(text: string, options: FromMarkdownOptions = {}): Promise<Presentation> {
  const deck = await Presentation.create(options);
  const available = new Set(deck.layouts);
  for (const spec of parseMarkdown(text)) {
    let layout = spec.layout || defaultLayout(spec);
    if (!available.has(layout)) layout = deck.matchLayout(layout, spec.title !== null, spec.paragraphs.length > 0);
    const slide = deck.addSlide(layout);
    if (spec.title !== null) {
      if (slide.title === null) throw new Error(`the "${layout}" layout doesn't show a title, for ${JSON.stringify(spec.title)}`);
      slide.title = spec.title;
    }
    if (spec.paragraphs.length) {
      if (slide.body === null) {
        throw new Error(`the "${layout}" layout doesn't show a body, for ${JSON.stringify(spec.paragraphs[0].text)}`);
      }
      slide.body = spec.paragraphs;
    }
    if (spec.subtitle !== null) slide.addSubtitle(spec.subtitle);
    if (spec.notes) slide.notes = spec.notes;
    if (spec.transition) {
      slide.setTransition(spec.transition, {
        duration: spec.transitionDuration ?? undefined,
        direction: spec.transitionDirection ?? undefined,
      });
    }
    if (spec.skipped) slide.skipped = true;
    placeTables(slide, spec);
    for (const image of spec.images) {
      const data = options.images ? await options.images(image.path) : await readImageFile(image.path, options.baseDir);
      const name = image.path.split(/[\\/]/).pop() || "image";
      if (image.position !== null) {
        slide.addImage(data, { position: image.position, size: image.size ?? undefined, description: image.description, placeholder: false, name });
      } else {
        slide.addImage(data, { description: image.description, name });
      }
    }
    for (const sample of slide.images.filter((i) => i.isSample)) slide.removeImage(sample);
    for (const { target, ...build } of spec.builds) slide.addBuild(target as "title" | "subtitle" | "body", build);
  }
  return deck;
}

/** Lay a slide's tables out side by side, below the title and any body text. */
function placeTables(slide: Slide, spec: SlideSpec): void {
  if (!spec.tables.length) return;
  const { width: w, height: h } = slide.presentation.size;
  const margin = w * 0.05;
  let top = h * (spec.title !== null ? 0.24 : 0.08);
  if (spec.paragraphs.length) top = h * 0.55;
  const gap = margin / 2;
  const width = (w - 2 * margin - gap * (spec.tables.length - 1)) / spec.tables.length;
  spec.tables.forEach((table, i) => {
    const rowHeight = Math.min(h * 0.06, (h - top - margin) / table.rows.length);
    slide.addTable(table.rows, {
      x: margin + i * (width + gap),
      y: top,
      width,
      height: rowHeight * table.rows.length,
      headerRows: table.headerRows,
    });
  });
}
