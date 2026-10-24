/** Read and write Keynote presentations straight from the .key file, without Keynote. */

import * as builds from "./builds.js";
import { CHART_TYPES, Chart, addChart, copyChart, type AddChartOptions } from "./charts.js";
import { Importer, ownedObjects, removeObjects } from "./clone.js";
import {
  Drawable,
  Shape,
  addExternalReference,
  addShape,
  componentIdOf,
  isSubtitleStyle,
  paragraphStyleName,
  styleNamed,
  subtitleStyle,
  removeExternalReference,
  removeFromSlide,
  type Color,
} from "./drawables.js";
import { toMarkdown, type ToMarkdownOptions } from "./markdown.js";
import * as media from "./media.js";
import { Package, remapReferences } from "./package.js";
import { clear, create, ensure, enumValue, has, sub, typeOf, type Message } from "./protobuf.js";
import * as slides from "./slides.js";
import { Table, addTable, copyTable, type AddTableOptions, type CellValue } from "./tables.js";
import { ASPECTS, loadTemplate, partsPackage, preload, templateFile, type Aspect } from "./templates.js";
import { Text, type Paragraph, type ParagraphInput } from "./text.js";

export type { Aspect } from "./templates.js";
export { themes } from "./templates.js";

/** A slide's transition. ``effect`` is ``null`` when there is no transition. */
export interface Transition {
  effect: string | null;
  duration: number;
  delay: number;
  automatic: boolean;
  /** Keynote's own name for the effect, e.g. ``"apple:dissolve"``. */
  effectId: string;
  /** e.g. ``"from left"``; ``null`` if it has none or isn't known. */
  direction: string | null;
}

export interface TransitionOptions {
  duration?: number;
  delay?: number;
  automatic?: boolean;
  /** ``"from left"``, ``"from right"``, ``"from top"`` or ``"from bottom"``, for effects that move. Wipe goes from left by default. */
  direction?: builds.Direction | string;
}

/** Transitions that take a direction, with the one Keynote uses when it leaves the field out. */
const TRANSITION_DIRECTIONAL: Record<string, string | null> = {
  "apple:wipe": "from left",
  "apple:push": null,
};

/** A transition or build for {@link Presentation.applyStyle}: an effect name, or its options. */
export type StyleTransition = string | ({ effect: string } & TransitionOptions);
export type StyleBuild = string | ({ effect: string } & builds.BuildOptions);

export interface ApplyStyleOptions {
  transition?: StyleTransition;
  titleBuild?: StyleBuild;
  subtitleBuild?: StyleBuild;
  bodyBuild?: StyleBuild;
  /** Slide indexes to style; every slide by default. */
  slides?: number[];
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
  /** @internal */
  readonly pkg: Package;
  /** @internal */
  readonly nodeId: number;
  /** @internal */
  readonly node: Message;
  /** @internal */
  readonly slideId: number;
  /** @internal */
  readonly slide: Message;

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
      direction: builds.directionName(a.direction, TRANSITION_DIRECTIONAL[a.effect] ?? null),
    };
  }

  /**
   * Set the transition into the next slide, e.g. ``setTransition("wipe", { duration: 0.75, direction: "from right" })``.
   *
   * ``effect`` is a name such as ``"dissolve"``, ``"wipe"``, ``"push"`` or
   * ``"magic move"``, Keynote's own id such as ``"apple:dissolve"``, or
   * ``null`` to remove the transition. Dissolve, wipe, push and magic move
   * are checked against real Keynote files; other names follow the same pattern.
   */
  setTransition(effect: string | null, options: TransitionOptions = {}): void {
    const attrs = ensure(ensure(this.slide, "transition"), "attributes");
    const a = ensure(attrs, "animationAttributes");
    const effectId = effectIdOf(effect);
    builds.setDirection(a, effectId, options.direction, TRANSITION_DIRECTIONAL, "transition");
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

  /** The slide's build animations, in the order they play. */
  get builds(): builds.Build[] {
    return builds.readBuilds(this);
  }

  /**
   * Animate ``target`` onto the slide: ``"title"``, ``"subtitle"``,
   * ``"body"``, a shape, image, table or chart, or its identifier.
   *
   * ``effect`` is a build effect such as ``"dissolve"`` (the default),
   * ``"move in"``, ``"wipe"`` or ``"fade and move"``, or options with
   * ``effect``, ``delivery`` (``"all at once"`` or ``"by bullet"``, the
   * default for a body with several paragraphs), ``duration``, ``kind``
   * (``"in"`` or ``"out"``), ``start`` (``"on click"``, ``"after previous"``
   * or ``"with previous"``), ``delay`` and ``direction``. Each build plays
   * after the ones added before it; ``delay`` is the seconds its first step
   * waits and, as in Keynote, every bullet starts the way ``start`` says.
   */
  addBuild(target: builds.BuildTarget = "body", effect: string | builds.BuildOptions = {}): builds.Build {
    return builds.addBuild(this, target, typeof effect === "string" ? { effect } : effect);
  }

  /** Remove every build from the slide. */
  clearBuilds(): void {
    builds.clearBuilds(this);
  }

  // --- shapes, tables and charts ---------------------------------------------

  /** Shapes, text boxes, tables and charts on the slide, back to front (not the title, body or images). */
  get drawables(): Drawable[] {
    return drawablesOf(this);
  }

  /** Shapes and text boxes. */
  get shapes(): Shape[] {
    return this.drawables.filter((d): d is Shape => d instanceof Shape);
  }

  get tables(): Table[] {
    return this.drawables.filter((d): d is Table => d instanceof Table);
  }

  get charts(): Chart[] {
    return this.drawables.filter((d): d is Chart => d instanceof Chart);
  }

  private defaultFrame(frame: FrameOptions, w0: number, h0: number): [number, number, number, number] {
    const { width: sw, height: sh } = this.presentation.size;
    const width = frame.width ?? w0;
    const height = frame.height ?? h0;
    return [frame.x ?? (sw - width) / 2, frame.y ?? (sh - height) / 2, width, height];
  }

  /**
   * Add a shape, in the middle of the slide unless ``x`` and ``y`` are given.
   *
   * ``kind`` is one of {@link SHAPE_KINDS}, such as ``"rectangle"``,
   * ``"rounded rectangle"``, ``"oval"``, ``"triangle"``, ``"star"`` or
   * ``"arrow"``. ``style`` picks one of the theme's six shape styles (0 to
   * 5); ``fill`` overrides its colour, e.g. ``"#3366ff"``. Positions and
   * sizes are in points from the slide's top left.
   */
  addShape(kind = "rectangle", options: AddShapeOptions = {}): Shape {
    const [x, y, width, height] = this.defaultFrame(options, 400, 300);
    return addShape(this, kind, x, y, width, height, { text: options.text, style: options.style, fill: options.fill });
  }

  /**
   * Give the slide a subtitle under its title, in the theme's Subtitle paragraph style.
   *
   * On layouts such as "Title", whose body placeholder is the subtitle
   * ("Presentation Subtitle"), this fills the body. Layouts such as Basic
   * White's "Title & Bullets" come with an empty subtitle text box, which
   * this fills. Otherwise it adds one that spans the title's width and tucks
   * under its last line, as Keynote places it. Builds can target it as
   * ``"subtitle"``. Returns the text box, or ``null`` when the subtitle is
   * the body placeholder.
   */
  addSubtitle(text: string | Iterable<ParagraphInput>): Shape | null {
    if (this.bodyIsSubtitle()) {
      if ((this.body ?? "").trim()) throw new Error(`slide ${this.index} already has a subtitle`);
      this.body = text;
      return null;
    }
    const existing = this.subtitleShape();
    if (existing !== null) {
      if (existing.text.trim()) throw new Error(`slide ${this.index} already has a subtitle`);
      existing.text = text;
      return existing;
    }
    const s = this.slide;
    const shown = new Set((s.drawables_z_order as Message[]).map((r) => r.identifier));
    if (!has(s, "titlePlaceholder") || !shown.has(s.titlePlaceholder.identifier)) {
      throw new Error(`the "${this.layout}" layout doesn't show a title for a subtitle to go under`);
    }
    const style = subtitleStyle(this.pkg);
    if (style === null) throw new Error("this theme has no Subtitle paragraph style");
    const size: number = this.pkg.get(styleNamed(this.pkg, style)).char_properties.font_size;
    let g: Message = this.pkg.get(s.titlePlaceholder.identifier);
    while (!has(g, "geometry")) g = g.super;
    g = g.geometry;
    // As in Basic White's "Title & Bullets": the subtitle's top is a fifth of
    // its font size above the title's bottom, and one line is 1.34 font sizes high.
    const y = g.position.y + g.size.height - 0.2 * size;
    const height = Math.round(size * 1.3383 * 1e4) / 1e4;
    return addShape(this, "text box", g.position.x, y, g.size.width, height, { text, paragraphStyle: style });
  }

  /** The subtitle under the title (see {@link addSubtitle}), or ``null`` if it has none or it is empty. */
  get subtitle(): string | null {
    if (this.bodyIsSubtitle()) return (this.body ?? "").trim() ? this.body : null;
    const shape = this.subtitleShape();
    return shape !== null && shape.text.trim() ? shape.text : null;
  }

  set subtitle(value: string | null) {
    if (this.bodyIsSubtitle()) {
      this.body = value ?? "";
      return;
    }
    const shape = this.subtitleShape();
    if (shape !== null) shape.text = value ?? "";
    else if (value) this.addSubtitle(value);
  }

  /** @internal */
  bodyIsSubtitle(): boolean {
    // Whether the layout's body placeholder is its subtitle, as on "Title" ("Presentation Subtitle").
    if (this.bodyText === null) return false;
    const storageId: number = this.pkg.deref(this.slide.bodyPlaceholder).super.owned_storage.identifier;
    return isSubtitleStyle(paragraphStyleName(this.pkg, storageId));
  }

  /** @internal */
  subtitleShape(): Shape | null {
    return this.shapes.find((d) => d.isSubtitle) ?? null;
  }

  /** Add a text box in the theme's text box style. */
  addTextBox(text: string | Iterable<ParagraphInput>, options: FrameOptions = {}): Shape {
    const [x, y, width, height] = this.defaultFrame(options, 600, 80);
    return addShape(this, "text box", x, y, width, height, { text });
  }

  /**
   * Add a chart of ``rows`` of values, one list per row name.
   *
   * ``chartType`` is one of {@link CHART_TYPES}: ``"column"``, ``"bar"``,
   * ``"line"``, ``"area"``, ``"pie"``, ``"donut"``, their ``"stacked"``
   * forms or ``"scatter"``. Each row is a data series unless ``seriesBy``
   * is ``"column"``, the default for pies and donuts: Keynote draws a pie
   * from the first value of each series, so the first row's values become
   * the slices. Pies are kept square. ``style`` picks one of the theme's six
   * chart styles; the legend shows when there is more than one series
   * unless ``legend`` says.
   */
  addChart(chartType: keyof typeof CHART_TYPES, rows: (number | null)[][], rowNames: string[], columnNames: string[], options: AddChartOptions = {}): Chart {
    const frame = this.defaultFrame(options, 900, 640);
    return addChart(this, chartType, rows, rowNames, columnNames, partsPackage(), frame, options);
  }

  /**
   * Add a table of ``rows``: arrays of text, numbers, ``true``/``false`` or ``null`` for an empty cell.
   *
   * The first ``headerRows`` rows (1 unless given) and ``headerColumns``
   * columns are headers. ``style`` picks one of the theme's six table
   * styles. The table is centred unless ``x`` and ``y`` are given; each row
   * is 64 points high unless ``height`` is given.
   */
  addTable(rows: CellValue[][], options: AddTableOptions = {}): Table {
    const nRows = rows.length;
    const nCols = Math.max(0, ...rows.map((r) => r.length));
    const { width: sw, height: sh } = this.presentation.size;
    const width = options.width ?? Math.min(sw - 120, 300.0 * Math.max(nCols, 1));
    const height = options.height ?? 64.0 * Math.max(nRows, 1);
    const x = options.x ?? (sw - width) / 2;
    const y = options.y ?? (sh - height) / 2;
    return addTable(this, rows, partsPackage(), x, y, { ...options, width, height });
  }

  /** Remove a shape, text box, table or chart from the slide. */
  deleteDrawable(drawable: Drawable): void {
    if (drawable.slide.slideId !== this.slideId) throw new Error("that drawable is on another slide");
    if (this.builds.some((b) => b.target === drawable.identifier)) throw new Error("remove the drawable's builds first (clearBuilds)");
    deleteDrawable(this, drawable);
  }

  // --- images ------------------------------------------------------------------

  /** The slide's images, back to front, including media placeholders. */
  get images(): media.Image[] {
    return media.readImages(this);
  }

  /** The layout's media placeholders on this slide, left to right and top to bottom. */
  get placeholders(): media.Image[] {
    return media.placeholders(this);
  }

  /**
   * Add a PNG, JPEG or GIF image from its bytes.
   *
   * With no ``position`` or ``size``, the image fills the slide's first
   * media placeholder that still shows the theme's sample photo, cropped to
   * it as Keynote does. Otherwise, or with ``placeholder: false``, it goes
   * on top of everything else: at ``position`` (top left, in points),
   * ``size`` wide and high (give one as ``null`` to keep the picture's
   * shape), and centred if no position is given. ``placeholder`` can also
   * name a placeholder, e.g. ``"Media-2"``.
   */
  addImage(source: media.ImageSource, options: media.AddImageOptions = {}): media.Image {
    return media.addImage(this, source, options);
  }

  /**
   * Put a new picture in place of ``image``: an {@link Image}, its index in
   * {@link images}, or a placeholder tag.
   *
   * A cropped image (such as a placeholder) keeps its crop, with the new
   * picture scaled to cover it. Otherwise the picture fits inside the old one's frame.
   */
  replaceImage(image: media.ImageTarget, source: media.ImageSource, options: { description?: string; name?: string } = {}): media.Image {
    return media.replaceImage(this, image, source, options);
  }

  /** Delete an image, and any builds on it. */
  removeImage(image: media.ImageTarget): void {
    media.removeImage(this, image);
  }

  toJSON() {
    const t = this.transition;
    return {
      index: this.index,
      layout: this.layout,
      title: this.title,
      subtitle: this.subtitle,
      body: this.body,
      notes: this.notes,
      skipped: this.skipped,
      transition: { effect: t.effect, duration: t.duration, delay: t.delay, automatic: t.automatic, direction: t.direction },
      builds: this.builds.map((b) => ({
        target: b.target,
        kind: b.kind,
        effect: b.effect,
        delivery: b.delivery,
        duration: b.duration,
        steps: b.steps,
        start: b.start,
        delay: b.delay,
        direction: b.direction,
      })),
      drawables: this.drawables.map((d) => d.toJSON()),
      images: this.images.map((i) => ({
        position: i.position,
        size: i.size,
        description: i.description,
        placeholder: i.placeholder,
        filename: i.filename,
      })),
    };
  }
}

/** Where to put a drawable, in points from the slide's top left. Centred when ``x`` and ``y`` aren't given. */
export interface FrameOptions {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
}

export interface AddShapeOptions extends FrameOptions {
  text?: string | Iterable<ParagraphInput>;
  /** One of the theme's six shape styles, 0 to 5. */
  style?: number;
  fill?: Color;
}

/** Every drawable on the slide besides its placeholders and images, back to front. */
function drawablesOf(slide: Slide): Drawable[] {
  const p = slide.pkg;
  const out: Drawable[] = [];
  for (const ref of slide.slide.drawables_z_order as Message[]) {
    if (!p.has(ref.identifier)) continue;
    let name: string;
    try {
      name = typeOf(p.get(ref.identifier));
    } catch {
      continue;
    }
    if (name === "TSWP.ShapeInfoArchive") out.push(new Shape(slide, ref.identifier));
    else if (name === "TST.TableInfoArchive") out.push(new Table(slide, ref.identifier));
    else if (name === "TSCH.ChartDrawableArchive") out.push(new Chart(slide, ref.identifier));
  }
  return out;
}

/** Remove a drawable and everything it owns, wherever in the package that is. */
function deleteDrawable(slide: Slide, drawable: Drawable): void {
  drawable.beforeDelete();
  removeFromSlide(slide, drawable.identifier);
  const ids = ownedObjects(slide.pkg, drawable.identifier, new Set([slide.slideId]));
  ids.push(...drawable.ownedElsewhere(ids));
  removeObjects(slide.pkg, ids);
}

/**
 * Give a duplicated slide its own copies of the original's tables and charts.
 *
 * Copying a slide's file copies its shapes, but tables and charts keep
 * objects in other files, which the copy would otherwise share.
 */
function unshareDrawables(original: Slide, copy: Slide): void {
  const copies = copy.drawables;
  const pairs = original.drawables
    .map((d, i): [Drawable, Drawable] => [d, copies[i]])
    .filter(([a, b]) => b !== undefined && (a instanceof Table || a instanceof Chart));
  if (!pairs.length) return;
  const p = copy.pkg;
  const importer = new Importer(p, p);
  const s = copy.slide;
  for (const [old, alias] of pairs) {
    const fresh = old instanceof Table ? copyTable(importer, old.identifier, original.slideId, copy) : copyChart(importer, old.identifier, original.slideId, copy);
    remapReferences(s, new Map([[alias.identifier, fresh.identifier]])); // drawables, z-order and the like
    for (const buildRef of s.builds as Message[]) {
      const build = p.deref(buildRef);
      if (build.drawable.identifier === alias.identifier) {
        build.drawable.identifier = fresh.identifier;
        p.markChanged(buildRef.identifier);
      }
    }
    p.removeObjectReference(copy.slideId, alias.identifier);
    p.addObjectReference(copy.slideId, fresh.identifier);
    const component = p.component(componentIdOf(p, copy.slideId));
    removeExternalReference(p, component, alias.identifier);
    addExternalReference(p, component, fresh.identifier);
    if (alias.identifier !== old.identifier) {
      // The chart itself was copied with the slide's file: drop that copy and what only it owns.
      const slideFile = p.fileOf(copy.slideId);
      removeObjects(p, ownedObjects(p, alias.identifier, new Set([copy.slideId])).filter((i) => p.fileOf(i) === slideFile));
    }
  }
  p.markChanged(copy.slideId);
}

export interface CreateOptions {
  /** A bundled theme (see {@link themes}). Defaults to ``"Basic White"``. */
  theme?: string;
  /** Defaults to ``"16:9"``. */
  aspect?: Aspect;
  /** The bundled theme deck's bytes, if you've loaded them yourself; ``theme`` and ``aspect`` are then ignored. */
  template?: Uint8Array;
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

// Node's modules, loaded only when a file path is used, so the rest works in a browser.
// A variable keeps bundlers from trying to include them in browser builds.
async function node(): Promise<{ fs: typeof import("node:fs/promises"); path: typeof import("node:path") }> {
  const fsName = "node:fs/promises";
  const pathName = "node:path";
  try {
    return { fs: await import(/* @vite-ignore */ fsName), path: await import(/* @vite-ignore */ pathName) };
  } catch {
    throw new Error("reading and writing files needs Node; in a browser use Presentation.fromBytes() and toBytes()");
  }
}

async function readPackage(path: string): Promise<Package> {
  const { fs, path: paths } = await node();
  if (!(await fs.stat(path)).isDirectory()) return Package.fromBytes(new Uint8Array(await fs.readFile(path)));
  // Older .key files can be folders rather than zips.
  const files = new Map<string, Uint8Array>();
  for (const entry of await fs.readdir(path, { recursive: true, withFileTypes: true })) {
    if (!entry.isFile()) continue;
    const full = paths.join(entry.parentPath, entry.name);
    files.set(paths.relative(path, full).split(paths.sep).join("/"), new Uint8Array(await fs.readFile(full)));
  }
  return new Package(files);
}

/** Load the parts deck for tables and charts, without failing if it can't be had. */
async function tryPreload(): Promise<void> {
  try {
    await preload();
  } catch {
    // addTable() and addChart() say so if they're used.
  }
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

  /** Open a ``.key`` file (Node only; in a browser use {@link fromBytes}). */
  static async open(path: string): Promise<Presentation> {
    const { path: paths } = await node();
    const full = paths.resolve(path);
    const [pkg] = await Promise.all([readPackage(full), tryPreload()]);
    return new Presentation(pkg, full);
  }

  /**
   * Read a ``.key`` file from its bytes, e.g. from an upload or a fetch().
   *
   * To add tables or charts to it, ``await preload()`` once first.
   */
  static fromBytes(bytes: Uint8Array): Presentation {
    return new Presentation(Package.fromBytes(bytes));
  }

  /** A new, empty presentation in one of the bundled themes (see {@link themes}). */
  static async create(options: CreateOptions = {}): Promise<Presentation> {
    const theme = options.theme ?? "Basic White";
    const aspect = options.aspect ?? "16:9";
    if (!ASPECTS.includes(aspect)) throw new Error(`aspect must be one of ${ASPECTS.join(", ")}, not "${aspect}"`);
    const [bytes] = await Promise.all([options.template ?? loadTemplate(templateFile(theme, aspect)), tryPreload()]);
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
    const slide = this.slides[index];
    // Tables and charts keep objects outside the slide's own file; remove those first.
    for (const drawable of slide.drawables) {
      if (drawable instanceof Table || drawable instanceof Chart) deleteDrawable(slide, drawable);
    }
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
    const copy = this.slides[to];
    unshareDrawables(new Slide(this, create("TSP.Reference", { identifier: nodeId }), -1), copy);
    return copy;
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
   * body text with indent levels, subtitle, presenter notes, transition,
   * skipped flag, and builds on its title, subtitle and body. Images, shapes, text boxes and
   * text formatting that differs from the layout's own are not carried over.
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
      const oldA = sub(sub(sub(old.slide, "transition"), "attributes"), "animationAttributes");
      if (has(oldA, "direction")) slide.slide.transition.attributes.animationAttributes.direction = oldA.direction;
      slide.skipped = old.skipped;
      if (old.subtitle !== null && slide.title !== null && slide.subtitle === null) slide.addSubtitle(old.subtitle);
      for (const b of old.builds) {
        if (typeof b.target !== "string") continue;
        const present = { title: slide.titleText, body: slide.bodyText, subtitle: slide.subtitle }[b.target];
        if (present === null) continue;
        const delivery = b.delivery.toLowerCase() in builds.DELIVERY_NAMES ? b.delivery.toLowerCase() : undefined;
        slide.addBuild(b.target, {
          effect: b.effectId,
          delivery,
          duration: b.duration,
          kind: b.kind,
          start: b.start,
          delay: b.delay,
          direction: b.direction ?? undefined,
        });
      }
      slide.touched();
    }
    this.package = target.package;
    this.showId = target.showId;
    this.show = target.show;
    this.prototypes = target.prototypes;
  }

  /**
   * Give every slide (or those in ``slides``) the same transition and builds.
   *
   * ``transition`` is an effect name or ``{ effect, duration, direction }``.
   * Each build is an effect name or ``{ effect, ...addBuild options }``, e.g.
   * ``{ effect: "wipe", start: "after previous", delay: 0.1 }``. A slide's
   * existing builds are replaced, and a build is left out where the slide
   * doesn't show that text or it is empty. Builds play title, then
   * subtitle, then body. On a layout whose body is its subtitle, such as
   * "Title", the body gets ``subtitleBuild``.
   */
  applyStyle(options: ApplyStyleOptions = {}): void {
    const { transition, titleBuild, subtitleBuild, bodyBuild } = options;
    const chosen = options.slides === undefined ? this.slides : options.slides.map((i) => this.slides[this.checkIndex(i)]);
    for (const slide of chosen) {
      if (transition !== undefined) {
        const { effect, ...rest } = typeof transition === "string" ? { effect: transition } : transition;
        slide.setTransition(effect, rest);
      }
      if (titleBuild === undefined && subtitleBuild === undefined && bodyBuild === undefined) continue;
      slide.clearBuilds();
      for (const [target, build] of [["title", titleBuild], ["subtitle", subtitleBuild], ["body", bodyBuild]] as const) {
        if (build === undefined || !(slide[target] ?? "").trim()) continue;
        if (target === "body" && slide.bodyIsSubtitle()) continue; // the body is the subtitle, built by subtitleBuild
        slide.addBuild(target, typeof build === "string" ? { effect: build } : build);
      }
    }
  }

  /** The presentation as Markdown (see ``toMarkdown``). */
  toMarkdown(options: ToMarkdownOptions = {}): string {
    return toMarkdown(this, options);
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

  /** Write the presentation as a ``.key`` file, to ``path`` or back where it came from (Node only; in a browser use {@link toBytes}). */
  async save(path?: string): Promise<void> {
    const target = path ?? this.path;
    if (target == null) throw new Error("no path to save to");
    const { fs, path: paths } = await node();
    await fs.writeFile(target, this.toBytes());
    this.path = paths.resolve(target);
  }
}
