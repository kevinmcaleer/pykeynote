/** Read and write Keynote presentations straight from the .key file, without Keynote. */

import { readFile, readdir, stat, writeFile } from "node:fs/promises";
import { readdirSync } from "node:fs";
import { join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

import { toMarkdown } from "./markdown.js";
import { Package } from "./package.js";
import { clear, ensure, enumValue, has, sub, type Message } from "./protobuf.js";
import * as slides from "./slides.js";
import { Text, type Paragraph, type ParagraphInput } from "./text.js";

/** A slide's transition. ``effect`` is ``null`` when there is no transition. */
export interface Transition {
  effect: string | null;
  duration: number;
  delay: number;
  automatic: boolean;
  /** Keynote's own name for the effect, e.g. ``"apple:dissolve"``. */
  effectId: string;
}

export interface TransitionOptions {
  duration?: number;
  delay?: number;
  automatic?: boolean;
}

function effectName(effectId: string): string | null {
  if (effectId === "" || effectId === "none") return null;
  const name = effectId.includes(":") ? effectId.slice(effectId.indexOf(":") + 1) : effectId;
  if (name.startsWith("magic-move")) return "magic move";
  return name.replaceAll("-", " ");
}

function effectIdOf(name: string | null | undefined): string {
  if (name == null || ["", "none", "no transition"].includes(name.trim().toLowerCase())) return "none";
  if (name.includes(":")) return name;
  const key = name.trim().toLowerCase().replace(/[_-]/g, " ");
  if (key === "magic move") return "apple:magic-move-implied-motion-path";
  return "apple:" + key.replaceAll(" ", "-");
}

/** Turn an identifier such as ``"21_BasicWhite"`` into ``"Basic White"``. */
function themeName(identifier: string): string {
  return identifier.replace(/^\d+_/, "").replace(/(?<=[a-z])(?=[A-Z])/g, " ");
}

const TRANSITION_ENUMS = "KN.TransitionAttributesArchive.TransitionCustomAttributes";

/** One slide, read from the file. */
export class Slide {
  private readonly pkg: Package;
  private readonly nodeId: number;
  private readonly node: Message;
  private readonly slideId: number;
  private readonly slide: Message;

  constructor(
    readonly presentation: Presentation,
    nodeRef: Message,
    readonly index: number,
  ) {
    this.pkg = presentation.package;
    this.nodeId = nodeRef.identifier;
    this.node = this.pkg.deref(nodeRef);
    this.slideId = this.node.slide.identifier;
    this.slide = this.pkg.get(this.slideId);
  }

  private placeholderText(field: "titlePlaceholder" | "bodyPlaceholder"): Text | null {
    if (!has(this.slide, field)) return null;
    const ref = this.slide[field];
    // A placeholder is shown only when it is part of the slide's drawables.
    if (!(this.slide.drawables_z_order as Message[]).some((r) => r.identifier === ref.identifier)) return null;
    const placeholder = this.pkg.deref(ref);
    return new Text(this.pkg, placeholder.super.owned_storage.identifier);
  }

  private setPlaceholderText(field: "titlePlaceholder" | "bodyPlaceholder", value: string | Iterable<ParagraphInput>): void {
    const text = this.placeholderText(field);
    if (text === null) {
      const what = field === "titlePlaceholder" ? "title" : "body";
      throw new Error(`the "${this.layout}" layout doesn't show a ${what} on slide ${this.index}`);
    }
    text.setParagraphs(typeof value === "string" ? value.split("\n") : value);
    this.touched();
  }

  /** @internal */
  touched(): void {
    // Keynote redraws thumbnails flagged as dirty when it opens the file.
    if (!this.node.thumbnailsAreDirty) {
      this.node.thumbnailsAreDirty = true;
      this.pkg.markChanged(this.nodeId);
    }
  }

  get titleText(): Text | null {
    return this.placeholderText("titlePlaceholder");
  }

  get bodyText(): Text | null {
    return this.placeholderText("bodyPlaceholder");
  }

  /** Title text, or ``null`` if this slide doesn't show a title. */
  get title(): string | null {
    const text = this.titleText;
    return text === null ? null : text.toString();
  }

  set title(value: string) {
    this.setPlaceholderText("titlePlaceholder", value);
  }

  /**
   * Body text with one line per paragraph, or ``null`` if this slide doesn't show a body.
   *
   * Assign a string with one line per paragraph, or an array of strings or
   * {@link Paragraph} objects to set indent levels too.
   */
  get body(): string | null {
    const text = this.bodyText;
    return text === null ? null : text.toString();
  }

  set body(value: string | Iterable<ParagraphInput>) {
    this.setPlaceholderText("bodyPlaceholder", value);
  }

  /** Body paragraphs with their indent level and whether they have a bullet. */
  get paragraphs(): Required<Paragraph>[] {
    return this.bodyText?.paragraphs ?? [];
  }

  private notesText(): Text | null {
    if (!has(this.slide, "note")) return null;
    const note = this.pkg.deref(this.slide.note);
    return new Text(this.pkg, note.containedStorage.identifier);
  }

  get notes(): string {
    return this.notesText()?.toString() ?? "";
  }

  set notes(value: string) {
    const text = this.notesText();
    if (text === null) throw new Error(`slide ${this.index} has no notes storage`);
    text.setParagraphs(value.split("\n"));
  }

  /** Name of the master slide this slide is based on. */
  get layout(): string {
    return this.pkg.deref(this.slide.template_slide).name;
  }

  get skipped(): boolean {
    return Boolean(this.node.isSkipped);
  }

  set skipped(value: boolean) {
    this.node.isSkipped = Boolean(value);
    this.pkg.markChanged(this.nodeId);
  }

  get transition(): Transition {
    const a = sub(sub(sub(this.slide, "transition"), "attributes"), "animationAttributes");
    return {
      effect: effectName(a.effect),
      duration: a.duration,
      delay: a.delay,
      automatic: a.is_automatic,
      effectId: a.effect,
    };
  }

  /**
   * Set the transition into the next slide, e.g. ``setTransition("dissolve", { duration: 1.5 })``.
   *
   * ``effect`` is a name such as ``"dissolve"``, ``"push"`` or ``"magic
   * move"``, Keynote's own id such as ``"apple:dissolve"``, or ``null`` to
   * remove the transition. Dissolve, push and magic move are checked against
   * real Keynote files; other names follow the same pattern.
   */
  setTransition(effect: string | null, options: TransitionOptions = {}): void {
    const attrs = ensure(ensure(this.slide, "transition"), "attributes");
    const a = ensure(attrs, "animationAttributes");
    const effectId = effectIdOf(effect);
    a.effect = effectId;
    for (const f of ["custom_magic_move_fade_unmatched_objects", "custom_timing_curve", "custom_text_delivery_type"]) {
      clear(attrs, f);
    }
    if (effectId.startsWith("apple:magic-move")) {
      // What Keynote 14.5 writes for a default Magic Move.
      attrs.custom_magic_move_fade_unmatched_objects = true;
      attrs.custom_timing_curve = enumValue(`${TRANSITION_ENUMS}TimingCurveType`, "TransitionCustomAttributesTimingCurveTypeEaseInEaseOut");
      attrs.custom_text_delivery_type = enumValue(`${TRANSITION_ENUMS}TextDeliveryType`, "TransitionCustomAttributesTextDeliveryTypeByObject");
    }
    if (options.duration !== undefined) a.duration = Number(options.duration);
    if (options.delay !== undefined) a.delay = Number(options.delay);
    if (options.automatic !== undefined) a.is_automatic = Boolean(options.automatic);
    this.pkg.markChanged(this.slideId);
    this.node.hasTransition = effectId !== "none";
    this.pkg.markChanged(this.nodeId);
  }

  get hasBuilds(): boolean {
    return this.slide.builds.length > 0;
  }

  toJSON() {
    const t = this.transition;
    return {
      index: this.index,
      layout: this.layout,
      title: this.title,
      body: this.body,
      notes: this.notes,
      skipped: this.skipped,
      transition: { effect: t.effect, duration: t.duration, delay: t.delay, automatic: t.automatic },
    };
  }
}

const TEMPLATES_DIR = fileURLToPath(new URL("../templates/", import.meta.url));

/** Slide sizes for new presentations: ``"16:9"`` is 1920 x 1080 (Wide), ``"4:3"`` is 1024 x 768 (Standard). */
export type Aspect = "16:9" | "4:3";
const ASPECTS: Aspect[] = ["16:9", "4:3"];

// Bundled templates are named "<theme>-<aspect>.key", e.g. "basic-white-16x9.key".
function templateFile(theme: string, aspect: string): string {
  return theme.trim().toLowerCase().replaceAll(" ", "-") + "-" + aspect.replace(":", "x") + ".key";
}

function bundled(): [string, string][] {
  return readdirSync(TEMPLATES_DIR)
    .filter((f) => f.endsWith(".key"))
    .sort()
    .map((f) => {
      const stem = f.slice(0, -4);
      const cut = stem.lastIndexOf("-");
      const name = stem
        .slice(0, cut)
        .split("-")
        .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
        .join(" ");
      return [name, stem.slice(cut + 1).replace("x", ":")];
    });
}

/** Names of the themes bundled with keynotejs, for {@link Presentation.create}. */
export function themes(): string[] {
  return [...new Set(bundled().map(([name]) => name))].sort();
}

export interface CreateOptions {
  /** A bundled theme (see {@link themes}). Defaults to ``"Basic White"``. */
  theme?: string;
  /** Defaults to ``"16:9"``. */
  aspect?: Aspect;
}

export interface ApplyThemeOptions {
  /** Defaults to whichever of ``"16:9"`` and ``"4:3"`` is closer to the current slide size. */
  aspect?: Aspect;
  /** Old layout names mapped to new ones where the default choice isn't wanted, e.g. ``{ Quote: "Statement" }``. */
  layouts?: Record<string, string>;
}

export interface AddSlideOptions {
  title?: string;
  body?: string | Iterable<ParagraphInput>;
  notes?: string;
  /** Where to put the slide. Defaults to the end. */
  index?: number;
}

async function readPackage(path: string): Promise<Package> {
  if (!(await stat(path)).isDirectory()) return Package.fromBytes(await readFile(path));
  // Older .key files can be folders rather than zips.
  const files = new Map<string, Uint8Array>();
  for (const entry of await readdir(path, { recursive: true, withFileTypes: true })) {
    if (!entry.isFile()) continue;
    const full = join(entry.parentPath, entry.name);
    files.set(relative(path, full).split(sep).join("/"), await readFile(full));
  }
  return new Package(files);
}

/** A Keynote presentation read from a ``.key`` file. Keynote isn't needed. */
export class Presentation {
  private showId: number;
  private show: Message;
  /** Slides kept only as models for addSlide(); hidden, and left out on save. */
  private prototypes = new Set<number>();

  /** The raw archives and files, for reaching what this class doesn't cover. */
  package: Package;

  constructor(
    pkg: Package,
    public path: string | null = null,
  ) {
    this.package = pkg;
    this.showId = pkg.get(1).show.identifier;
    this.show = pkg.get(this.showId);
  }

  /** Open a ``.key`` file. */
  static async open(path: string): Promise<Presentation> {
    const full = resolve(path);
    return new Presentation(await readPackage(full), full);
  }

  /** Read a ``.key`` file from its bytes, e.g. from an upload or a fetch(). */
  static fromBytes(bytes: Uint8Array): Presentation {
    return new Presentation(Package.fromBytes(bytes));
  }

  /** A new, empty presentation in one of the bundled themes (see {@link themes}). */
  static async create(options: CreateOptions = {}): Promise<Presentation> {
    const theme = options.theme ?? "Basic White";
    const aspect = options.aspect ?? "16:9";
    if (!ASPECTS.includes(aspect)) throw new Error(`aspect must be one of ${ASPECTS.join(", ")}, not "${aspect}"`);
    const path = join(TEMPLATES_DIR, templateFile(theme, aspect));
    let bytes: Uint8Array;
    try {
      bytes = await readFile(path);
    } catch {
      const available = bundled()
        .map(([n, a]) => `${n} (${a})`)
        .join(", ");
      throw new Error(`no bundled theme "${theme}" at ${aspect}; available: ${available}`);
    }
    const pres = Presentation.fromBytes(bytes);
    pres.prototypes = new Set(pres.nodeIds(true));
    return pres;
  }

  private nodeIds(includePrototypes = false): number[] {
    const ids = (this.show.slideTree.slides as Message[]).map((ref) => ref.identifier as number);
    return includePrototypes ? ids : ids.filter((i) => !this.prototypes.has(i));
  }

  /** Position in the full slide tree of the visible slide at ``index``. */
  private treeIndex(index: number): number {
    const visible = this.nodeIds();
    return this.nodeIds(true).indexOf(visible[index]);
  }

  get slides(): Slide[] {
    const refs = (this.show.slideTree.slides as Message[]).filter((r) => !this.prototypes.has(r.identifier));
    return refs.map((ref, i) => new Slide(this, ref, i));
  }

  get length(): number {
    return this.nodeIds().length;
  }

  /** The slide at ``index``; negative indexes count from the end. */
  slide(index: number): Slide {
    return this.slides[this.checkIndex(index)];
  }

  [Symbol.iterator](): Iterator<Slide> {
    return this.slides[Symbol.iterator]();
  }

  // --- changing the slide list ---------------------------------------------

  private checkIndex(index: number, allowEnd = false): number {
    const count = this.length;
    const limit = count + (allowEnd ? 1 : 0);
    if (!Number.isInteger(index)) throw new RangeError(`slide index must be an integer, not ${index}`);
    if (index < 0) index += limit;
    if (index < 0 || index >= limit) throw new RangeError(`slide index ${index} out of range for ${count} slides`);
    return index;
  }

  /** Move the slide at ``from`` so it ends up at ``to``. */
  moveSlide(from: number, to: number): void {
    from = this.checkIndex(from);
    to = this.checkIndex(to);
    const visible = this.nodeIds();
    const [node] = visible.splice(from, 1);
    visible.splice(to, 0, node);
    const prototypes = this.nodeIds(true).filter((i) => this.prototypes.has(i));
    slides.setTree(this.package, this.showId, [...prototypes, ...visible]);
  }

  deleteSlide(index: number): void {
    index = this.checkIndex(index);
    slides.deleteSlide(this.package, this.showId, this.treeIndex(index));
  }

  /** Copy the slide at ``index``. The copy goes right after it unless ``to`` is given. */
  duplicateSlide(index: number, to?: number): Slide {
    index = this.checkIndex(index);
    const target = to === undefined ? index + 1 : this.checkIndex(to, true);
    return this.copyNode(this.nodeIds()[index], target);
  }

  private copyNode(nodeId: number, to: number): Slide {
    const full = this.nodeIds(true);
    const visible = this.nodeIds();
    const treeTo = to >= visible.length ? full.length : full.indexOf(visible[to]);
    slides.duplicateSlide(this.package, this.showId, full.indexOf(nodeId), treeTo);
    return this.slides[to];
  }

  /**
   * Add a slide with the given layout, at the end unless ``index`` is given.
   *
   * The new slide is copied from an existing slide with that layout, so it
   * keeps that slide's look. Presentations made with {@link create} have one
   * of every layout to copy from. For other presentations, at least one
   * slide must already use the layout.
   */
  addSlide(layout = "Title & Bullets", options: AddSlideOptions = {}): Slide {
    const { title, body, notes } = options;
    const to = options.index === undefined ? this.length : this.checkIndex(options.index, true);
    const source = this.findLayout(layout);
    const slide = this.copyNode(source, to);
    if (slide.title !== null) slide.title = title ?? "";
    if (slide.body !== null) slide.body = body ?? "";
    if (notes !== undefined || slide.notes) slide.notes = notes ?? "";
    if (title !== undefined && slide.title === null) throw new Error(`the "${layout}" layout doesn't show a title`);
    if (body !== undefined && slide.body === null) throw new Error(`the "${layout}" layout doesn't show a body`);
    return slide;
  }

  private findLayout(layout: string): number {
    const p = this.package;
    const layoutOf = (nodeId: number): string => p.deref(p.deref(p.get(nodeId).slide).template_slide).name;
    const candidates = [...this.prototypes, ...this.nodeIds()].filter((n) => layoutOf(n) === layout);
    if (!candidates.length) {
      throw new Error(`no slide uses the "${layout}" layout to copy from; layouts here: ${this.layouts.join(", ")}`);
    }
    return candidates[0];
  }

  /** Slide size in points. */
  get size(): { width: number; height: number } {
    return { width: Math.trunc(this.show.size.width), height: Math.trunc(this.show.size.height) };
  }

  /** Theme name, e.g. ``"Basic White"``. */
  get theme(): string {
    return themeName(this.showTheme.super.theme_identifier);
  }

  private get showTheme(): Message {
    return this.package.deref(this.show.theme);
  }

  /** Names of the master slides in this presentation's theme, in order. */
  get layouts(): string[] {
    const p = this.package;
    return (this.showTheme.templates as Message[]).map((ref) => p.deref(p.deref(ref).slide).name);
  }

  /** For each layout this presentation has a slide for, whether it shows ``[title, body]``. */
  private layoutShows(): Map<string, [boolean, boolean]> {
    const shows = new Map<string, [boolean, boolean]>();
    for (const ref of this.show.slideTree.slides as Message[]) {
      const slide = new Slide(this, ref, -1);
      if (!shows.has(slide.layout)) shows.set(slide.layout, [slide.title !== null, slide.body !== null]);
    }
    return shows;
  }

  /**
   * The layout here that best stands in for ``layout`` from another theme.
   *
   * A layout with the same name is used when it shows a title and a body
   * wherever they're needed (``title`` and ``body`` say which are).
   * Otherwise the layout is picked by what it shows: "Title & Bullets" for a
   * title and body, "Bullets" for a body alone, "Title Only" for a title
   * alone, and "Blank" for neither.
   */
  matchLayout(layout: string, title = false, body = false): string {
    const shows = this.layoutShows();
    const fits = (name: string): boolean => {
      const s = shows.get(name);
      return s !== undefined && (s[0] || !title) && (s[1] || !body);
    };
    if (fits(layout)) return layout;
    const fallbacks =
      title && body ? ["Title & Bullets", "Title, Bullets & Photo", "Title"]
      : body ? ["Bullets", "Statement", "Title & Bullets"]
      : title ? ["Title Only", "Section", "Title"]
      : ["Blank", "Title Only"];
    const found = [...fallbacks, ...this.layouts].find(fits);
    if (found === undefined) throw new Error(`no layout in the "${this.theme}" theme can stand in for "${layout}"`);
    return found;
  }

  /**
   * Switch to one of the bundled themes (see {@link themes}), keeping the content.
   *
   * Each slide is rebuilt on the new theme's layout with the same name, or
   * the closest match (see {@link matchLayout}), and keeps its title and
   * body text with indent levels, presenter notes, transition and skipped
   * flag. Builds, images, shapes, text boxes and text formatting that
   * differs from the layout's own are not carried over.
   */
  async applyTheme(theme: string, options: ApplyThemeOptions = {}): Promise<void> {
    let aspect = options.aspect;
    if (aspect === undefined) {
      const { width, height } = this.size;
      aspect = width / height < (16 / 9 + 4 / 3) / 2 ? "4:3" : "16:9";
    }
    const layouts = options.layouts ?? {};
    const target = await Presentation.create({ theme, aspect });
    for (const old of this.slides) {
      const title = old.titleText;
      const body = old.bodyText;
      const wanted = layouts[old.layout];
      if (wanted !== undefined && !target.layouts.includes(wanted)) {
        throw new Error(`no "${wanted}" layout in the "${theme}" theme; layouts: ${target.layouts.join(", ")}`);
      }
      const layout = wanted ?? target.matchLayout(old.layout, title !== null, body !== null);
      const slide = target.addSlide(layout);
      if (title !== null) slide.titleText?.setParagraphs(title.paragraphs.length ? title.paragraphs : [""]);
      if (body !== null) slide.bodyText?.setParagraphs(body.paragraphs.length ? body.paragraphs : [""]);
      slide.notes = old.notes;
      const t = old.transition;
      slide.setTransition(t.effectId, { duration: t.duration, delay: t.delay, automatic: t.automatic });
      slide.skipped = old.skipped;
      slide.touched();
    }
    this.package = target.package;
    this.showId = target.showId;
    this.show = target.show;
    this.prototypes = target.prototypes;
  }

  toMarkdown(): string {
    return toMarkdown(this);
  }

  /** The presentation as ``.key`` file bytes. */
  toBytes(): Uint8Array {
    if (!this.nodeIds().length) throw new Error("a presentation needs at least one slide");
    let pkg = this.package;
    if (this.prototypes.size) {
      // Save a copy without the model slides, so this object can keep adding slides.
      pkg = Package.fromBytes(pkg.toBytes());
      const showId: number = pkg.get(1).show.identifier;
      for (const nodeId of this.prototypes) {
        const tree = (pkg.get(showId).slideTree.slides as Message[]).map((r) => r.identifier);
        slides.deleteSlide(pkg, showId, tree.indexOf(nodeId));
      }
    }
    return pkg.toBytes();
  }

  /** Write the presentation as a ``.key`` file, to ``path`` or back where it came from. */
  async save(path?: string): Promise<void> {
    const target = path ?? this.path;
    if (target == null) throw new Error("no path to save to");
    await writeFile(target, this.toBytes());
    this.path = resolve(target);
  }
}
