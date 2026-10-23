/**
 * Convert between presentations and Markdown.
 *
 * Each slide becomes a block, and blocks are separated by ``---``:
 *
 *     <!-- layout: Title & Bullets -->
 *     <!-- transition: dissolve 1.5s -->
 *     # Slide title
 *
 *     - A bullet
 *       - An indented bullet
 *
 *     A paragraph without a bullet
 *
 *     ???
 *     Presenter notes
 *
 * Slide settings go in HTML comments, so the Markdown still renders cleanly
 * elsewhere. Notes follow a line holding only ``???``, as in remark.js.
 */

import { Presentation, type Aspect, type Slide } from "./document.js";
import type { Paragraph } from "./text.js";

const SLIDE_SEPARATOR = "---";
const NOTES_MARKER = "???";

// A plain paragraph starting like this would read as Markdown syntax.
const NEEDS_ESCAPE = /^(#|[-*+] |\d+[.)] |>|---|\?\?\?|<!--)/;

/** Format like Python's ``f"{value:g}s"``: 1.5 is "1.5s", 1.0 is "1s". */
function fmtSeconds(value: number): string {
  return `${Number(value.toPrecision(6))}s`;
}

export function slideToMarkdown(slide: Slide): string {
  const lines: string[] = [`<!-- layout: ${slide.layout} -->`];
  const t = slide.transition;
  if (t.effect) lines.push(`<!-- transition: ${t.effect} ${fmtSeconds(t.duration)} -->`);
  if (slide.skipped) lines.push("<!-- skipped -->");

  const title = slide.title;
  if (title !== null && title.trim()) lines.push("# " + title.trim().split(/\s+/).join(" "));

  const body: string[] = [];
  for (const para of slide.paragraphs) {
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

  const notes = slide.notes.trim();
  if (notes) lines.push("", NOTES_MARKER, notes);
  return lines.join("\n") + "\n";
}

export function toMarkdown(presentation: Presentation): string {
  return presentation.slides.map(slideToMarkdown).join(`\n${SLIDE_SEPARATOR}\n\n`);
}

// --- Markdown to a presentation -------------------------------------------------

const COMMENT = /^<!--\s*(.*?)\s*-->$/;
const HEADING = /^#{1,2}\s+(.*)$/;
const BULLET = /^(\s*)(?:[-*+]|\d+[.)])\s+(.*)$/;
const TRANSITION = /^(.*?)(?:\s+([\d.]+)\s*s)?$/;

/** One slide parsed from Markdown, before it is added to a deck. */
export interface SlideSpec {
  layout: string | null;
  title: string | null;
  paragraphs: Required<Paragraph>[];
  notes: string;
  transition: string | null;
  transitionDuration: number | null;
  skipped: boolean;
}

/** The layout a slide gets when its Markdown doesn't name one. */
export function defaultLayout(spec: SlideSpec): string {
  const bulleted = spec.paragraphs.some((p) => p.bulleted);
  if (spec.title && spec.paragraphs.length) return bulleted ? "Title & Bullets" : "Title";
  if (spec.title) return "Title Only";
  if (spec.paragraphs.length) return bulleted ? "Bullets" : "Statement";
  return "Blank";
}

function clean(text: string): string {
  text = text.trim().replaceAll("<br>", "\n").replaceAll("<br/>", "\n").replaceAll("<br />", "\n");
  return text.startsWith("\\") ? text.slice(1) : text;
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
      paragraphs: [],
      notes: "",
      transition: null,
      transitionDuration: null,
      skipped: false,
    };
    let notes: string[] | null = null;
    const pending: string[] = []; // lines of a plain paragraph being collected

    const flush = () => {
      if (pending.length) {
        spec.paragraphs.push({ text: clean(pending.map((s) => s.trim()).join(" ")), level: 0, bulleted: false });
        pending.length = 0;
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
        } else if (key === "skipped") {
          spec.skipped = !["false", "no", "0"].includes(value.toLowerCase());
        }
        continue;
      }
      const heading = HEADING.exec(stripped);
      if (heading && spec.title === null && !spec.paragraphs.length && !pending.length) {
        spec.title = clean(heading[1]);
        continue;
      }
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
}

/**
 * Build a new presentation from Markdown in the {@link toMarkdown} format.
 *
 * A slide without a ``layout`` comment gets one from its content: title and
 * bullets give "Title & Bullets", a title alone "Title Only", and so on.
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
    if (spec.notes) slide.notes = spec.notes;
    if (spec.transition) slide.setTransition(spec.transition, { duration: spec.transitionDuration ?? undefined });
    if (spec.skipped) slide.skipped = true;
  }
  return deck;
}
