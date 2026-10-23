/**
 * Reading and rewriting the text in a Keynote text storage (``TSWP.StorageArchive``).
 *
 * A storage keeps its text as one string, with paragraphs ended by ``\r``.
 * Formatting lives in attribute tables, lists of ``(character_index, value)``
 * entries where each value holds until the next entry. Character indexes count
 * UTF-16 code units, as JavaScript strings do.
 *
 * Keynote expects some tables to change only at paragraph starts, and
 * ``table_para_style`` to hold exactly one entry per paragraph. Getting these
 * wrong can make Keynote draw a text box 2^16 points tall or crash, so
 * {@link Text.setParagraphs} rebuilds them all.
 */

import type { Package } from "./package.js";
import { clone, encode, has, type Message } from "./protobuf.js";

const PARAGRAPH = "\r"; // end of paragraph
const LINE_BREAK = " "; // line break inside a paragraph (shift-return)
const ATTACHMENT = "￼"; // stands in for an inline object, such as an image

// Tables whose runs start at paragraph boundaries. table_para_style is
// handled separately, because it needs an entry for every paragraph.
const PARAGRAPH_TABLES = [
  "table_para_data",
  "table_list_style",
  "table_para_starts",
  "table_para_bidi",
  "table_drop_cap_style",
  "table_layout_style",
];

// Tables of character runs. New text takes on the formatting of the start of
// the old text.
const CHARACTER_TABLES = [
  "table_char_style",
  "table_language",
  "table_dictation",
  "table_highlight",
  "table_insertion",
  "table_deletion",
  "table_bookmark",
  "table_rubyfield",
  "table_tatechuyoko",
  "table_section",
];

// Tables that tie objects to particular characters. Rewriting text that has
// any of these would leave them pointing at the wrong place.
const ANCHORED_TABLES = [
  "table_attachment",
  "table_smartfield",
  "table_footnote",
  "table_overlapping_highlight",
  "table_pencil_annotation",
];

/** The text holds something keynotejs can't rewrite safely yet, such as an inline image. */
export class UnsupportedTextError extends Error {
  override name = "UnsupportedTextError";
}

/** One paragraph of text. ``level`` is the list indent level, from 0. */
export interface Paragraph {
  text: string;
  level?: number;
  bulleted?: boolean;
}

/** A string keeps the indent level of the paragraph it replaces; a {@link Paragraph} sets its own. */
export type ParagraphInput = string | Paragraph;

/** The text in one storage archive. */
export class Text {
  private storage: Message;

  constructor(
    private pkg: Package,
    readonly identifier: number,
  ) {
    this.storage = pkg.get(identifier);
  }

  get raw(): string {
    return (this.storage.text as string[]).join("");
  }

  toString(): string {
    return this.paragraphs.map((p) => p.text).join("\n");
  }

  get paragraphs(): Required<Paragraph>[] {
    const raw = this.raw;
    if (!raw) return [];
    const chunks = raw.split(PARAGRAPH);
    const starts = startsOf(chunks);
    return chunks.map((chunk, i) => {
      const level = active(this.storage.table_para_data?.entries ?? [], starts[i]);
      const listStyle = active(this.storage.table_list_style?.entries ?? [], starts[i]);
      return {
        text: chunk.replaceAll(ATTACHMENT, "").replaceAll(LINE_BREAK, "\n"),
        level: level ? level.first : 0,
        bulleted: this.isBulleted(listStyle),
      };
    });
  }

  private isBulleted(entry: Message | undefined): boolean {
    if (!entry || !has(entry, "object")) return false;
    const style = this.pkg.deref(entry.object);
    const strings: unknown[] | undefined = style.strings;
    const labelTypes: number[] | undefined = style.label_types;
    return Boolean(strings?.length) || Boolean(labelTypes?.some((t) => t !== 0));
  }

  /**
   * Replace the text, keeping the formatting.
   *
   * New paragraphs beyond the old count copy the formatting of the old last
   * paragraph. A ``"\n"`` inside a paragraph becomes a line break.
   * ``bulleted`` is ignored for now, since bullets come from the layout.
   */
  setParagraphs(paragraphs: Iterable<ParagraphInput>): void {
    const st = this.storage;
    const items = [...paragraphs].map((p) => (typeof p === "string" ? { text: p, level: -1 } : { text: p.text, level: p.level ?? 0 }));
    for (const p of items) {
      if (p.text.includes(PARAGRAPH) || p.text.includes(ATTACHMENT)) {
        throw new Error(`paragraph text can't contain "\\r" or U+FFFC: ${JSON.stringify(p.text)}`);
      }
    }
    for (const name of ANCHORED_TABLES) {
      if (has(st, name) && st[name].entries.length > 0) {
        throw new UnsupportedTextError(`this text holds inline objects or annotations (${name}), which can't be rewritten yet`);
      }
    }

    const oldChunks = this.raw ? this.raw.split(PARAGRAPH) : [""];
    const oldStarts = startsOf(oldChunks);
    let texts = items.map((p) => p.text.replaceAll("\n", LINE_BREAK));
    if (texts.length === 0) texts = [""];
    const newStarts = startsOf(texts);
    const source = (j: number) => oldStarts[Math.min(j, oldStarts.length - 1)];

    // One table_para_style entry per paragraph.
    if (has(st, "table_para_style")) {
      const table = st.table_para_style;
      const old: Message[] = table.entries;
      table.entries = newStarts.map((start, j) => copyEntry(exact(old, source(j)) ?? active(old, source(j))!, start));
    }

    for (const name of PARAGRAPH_TABLES) {
      if (!has(st, name)) continue;
      const table = st[name];
      const old: Message[] = table.entries;
      if (!old.length) continue;
      const entries: Message[] = [];
      newStarts.forEach((start, j) => {
        const src = active(old, source(j));
        if (!src) return;
        const entry = copyEntry(src, start);
        if (name === "table_para_data" && j < items.length && items[j].level >= 0) entry.first = items[j].level;
        if (!entries.length || !sameValue(entries[entries.length - 1], entry)) entries.push(entry);
      });
      table.entries = entries;
    }

    for (const name of CHARACTER_TABLES) {
      if (!has(st, name)) continue;
      const table = st[name];
      const first = active(table.entries, 0);
      table.entries = first ? [copyEntry(first, 0)] : [];
    }

    const joined = texts.join(PARAGRAPH);
    st.text = joined ? [joined] : [];
    this.pkg.markChanged(this.identifier);
  }
}

function startsOf(chunks: string[]): number[] {
  const starts: number[] = [];
  let offset = 0;
  for (const chunk of chunks) {
    starts.push(offset);
    offset += chunk.length + 1;
  }
  return starts;
}

/** The table entry in force at ``index``. */
function active(entries: Message[], index: number): Message | undefined {
  let current: Message | undefined;
  for (const e of entries) {
    if (e.character_index > index) break;
    current = e;
  }
  return current;
}

function exact(entries: Message[], index: number): Message | undefined {
  return entries.find((e) => e.character_index === index);
}

function copyEntry(entry: Message, index: number): Message {
  const copy = clone(entry);
  copy.character_index = index;
  return copy;
}

function sameValue(a: Message, b: Message): boolean {
  const ka = encode(copyEntry(a, 0));
  const kb = encode(copyEntry(b, 0));
  return ka.length === kb.length && ka.every((x, i) => x === kb[i]);
}
