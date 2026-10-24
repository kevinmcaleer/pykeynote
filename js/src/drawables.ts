/**
 * Things drawn on a slide besides its title and body: shapes, text boxes, tables and charts.
 *
 * A slide lists what it draws in ``KN.SlideArchive.owned_drawables`` and, back
 * to front, ``drawables_z_order``. A shape or text box is a
 * ``TSWP.ShapeInfoArchive``: a frame, a path for its outline, a shape style
 * and a text storage. It lives in the slide's own component file, along with
 * the two empty ``TSD.StandinCaptionArchive`` objects Keynote gives every
 * drawable for its title and caption.
 *
 * New shapes use the theme's own styles, found by the names every Keynote
 * theme gives them (``shape-0-shapestyle`` and so on) in the document
 * stylesheet's ``identifier_to_style_map``. A shape that refers to an object
 * in another component, such as a style, needs a matching entry in its
 * slide component's ``external_references``.
 */

import type { Slide } from "./document.js";
import { METADATA_ID, addUuid, makeHeader, type Package } from "./package.js";
import { create, enumValue, ensure, has, sub, typeOf, type Message } from "./protobuf.js";
import { Text, type ParagraphInput } from "./text.js";

export const STYLESHEET_FILE = "Index/DocumentStylesheet.iwa";

// Message types and versions, as Keynote 14.5 writes them.
const SHAPE_INFO: [number, number[]] = [2011, [1, 0, 5]];
const STORAGE: [number, number[]] = [2001, [1, 0, 5]];
const CAPTION: [number, number[]] = [3097, [10, 1, 0]];
const SHAPE_STYLE: [number, number[]] = [2025, [1, 0, 5]];

/** ``"#3366ff"``, ``"#36f"``, a name such as ``"blue"``, or ``[r, g, b]`` or ``[r, g, b, a]`` from 0 to 1. */
export type Color = string | [number, number, number] | [number, number, number, number];

const ref = (identifier: number): Message => create("TSP.Reference", { identifier });

// --- styles -------------------------------------------------------------------

export function stylesheetId(pkg: Package): number {
  return pkg.componentForFile(STYLESHEET_FILE).identifier;
}

/** The theme's styles by their names, e.g. ``"shape-0-shapestyle"``. */
export function namedStyles(pkg: Package): Map<string, number> {
  const sheet = pkg.get(stylesheetId(pkg));
  return new Map((sheet.identifier_to_style_map as Message[]).map((e) => [e.identifier, e.style.identifier]));
}

export function styleNamed(pkg: Package, name: string): number {
  const found = namedStyles(pkg).get(name);
  if (found === undefined) throw new Error(`this theme has no "${name}" style`);
  return found;
}

/** The name of the theme's main subtitle paragraph style, e.g. ``"text-2-paragraphstyle-Subtitle"``. */
export function subtitleStyle(pkg: Package): string | null {
  const names = [...namedStyles(pkg).keys()].filter((n) => /^text-\d+-paragraphstyle-Subtitle$/.test(n));
  if (!names.length) return null;
  return names.reduce((a, b) => (Number(a.split("-")[1]) <= Number(b.split("-")[1]) ? a : b));
}

/**
 * A new style based on ``parentId`` that can override some of its properties.
 *
 * This is what Keynote makes when you change one shape's fill, say.
 */
export function addVariationStyle(pkg: Package, parentId: number): [number, Message] {
  const parent = pkg.get(parentId);
  const sheetId = stylesheetId(pkg);
  const styleId = pkg.newIdentifier();
  const style = create(typeOf(parent), {
    super: create("TSD.ShapeStyleArchive", {
      super: create("TSS.StyleArchive", { parent: ref(parentId), is_variation: true, stylesheet: ref(sheetId) }),
      override_count: 0,
    }),
  });
  pkg.addSegment(STYLESHEET_FILE, { header: makeHeader(styleId, SHAPE_STYLE[0], SHAPE_STYLE[1], [parentId]), objects: [style] });
  const sheet = pkg.get(sheetId);
  sheet.styles.push(ref(styleId));
  const entry = (sheet.parent_to_children_style_map as Message[]).find((e) => e.parent.identifier === parentId);
  if (entry) entry.children.push(ref(styleId));
  else sheet.parent_to_children_style_map.push(create("TSS.StylesheetArchive.StyleChildrenEntry", { parent: ref(parentId), children: [ref(styleId)] }));
  pkg.addObjectReference(sheetId, styleId);
  pkg.markChanged(sheetId);
  addUuid(pkg.componentForFile(STYLESHEET_FILE), styleId);
  return [styleId, style];
}

const NAMED_COLORS: Record<string, [number, number, number]> = {
  black: [0, 0, 0],
  white: [1, 1, 1],
  red: [1, 0.23, 0.19],
  orange: [1, 0.58, 0],
  yellow: [1, 0.8, 0],
  green: [0.2, 0.78, 0.35],
  blue: [0, 0.48, 1],
  purple: [0.69, 0.32, 0.87],
  pink: [1, 0.18, 0.33],
  gray: [0.56, 0.56, 0.58],
  grey: [0.56, 0.56, 0.58],
};

/** A {@link Color} as ``[r, g, b, a]`` from 0 to 1. */
export function parseColor(value: Color): [number, number, number, number] {
  if (typeof value === "string") {
    let v = value.trim().toLowerCase();
    if (v in NAMED_COLORS) return [...NAMED_COLORS[v], 1];
    if (v.startsWith("#")) {
      v = v.slice(1);
      if (v.length === 3 || v.length === 4) v = [...v].map((c) => c + c).join("");
      if ((v.length === 6 || v.length === 8) && /^[0-9a-f]+$/.test(v)) {
        const parts = (v.match(/../g) as string[]).map((h) => parseInt(h, 16) / 255);
        return [parts[0], parts[1], parts[2], parts.length === 4 ? parts[3] : 1];
      }
    }
    throw new Error(`not a colour: ${JSON.stringify(value)}`);
  }
  const parts = [...value].map(Number);
  if (![3, 4].includes(parts.length) || !parts.every((x) => x >= 0 && x <= 1)) {
    throw new Error(`a colour needs 3 or 4 values from 0 to 1, not ${JSON.stringify(value)}`);
  }
  return [parts[0], parts[1], parts[2], parts.length === 4 ? parts[3] : 1];
}

export function colorHex(color: Message): string {
  return "#" + [color.r, color.g, color.b].map((c: number) => Math.round(c * 255).toString(16).padStart(2, "0")).join("");
}

function newColor(rgba: [number, number, number, number]): Message {
  const [r, g, b, a] = rgba;
  return create("TSP.Color", {
    model: enumValue("TSP.Color.ColorModel", "rgb"),
    r,
    g,
    b,
    a,
    rgbspace: enumValue("TSP.Color.RGBColorSpace", "srgb"),
  });
}

// --- components ---------------------------------------------------------------

export function componentIdOf(pkg: Package, identifier: number): number {
  return pkg.componentForFile(pkg.fileOf(identifier)).identifier;
}

/** Record that ``component`` refers to ``target``, an object in another component. */
export function addExternalReference(pkg: Package, component: Message, target: number, weak = false): void {
  const targetComponent = componentIdOf(pkg, target);
  if (targetComponent === component.identifier) return;
  for (const e of component.external_references as Message[]) {
    const sameObject = has(e, "object_identifier") ? e.object_identifier === target : target === targetComponent;
    if (e.component_identifier === targetComponent && sameObject && e.is_weak === weak) return;
  }
  const e = create("TSP.ComponentExternalReference", { component_identifier: targetComponent });
  if (target !== targetComponent) e.object_identifier = target;
  if (weak) e.is_weak = true;
  component.external_references.push(e);
  pkg.markChanged(METADATA_ID);
}

/** Forget that ``component`` refers to the object ``target``. */
export function removeExternalReference(pkg: Package, component: Message, target: number): void {
  const refs = (component.external_references as Message[]).filter((e) => !(has(e, "object_identifier") && e.object_identifier === target));
  if (refs.length !== component.external_references.length) {
    component.external_references = refs;
    pkg.markChanged(METADATA_ID);
  }
}

/** Draw the drawable ``rootId`` in front of everything else. */
export function placeOnSlide(slide: Slide, rootId: number): void {
  const s = slide.slide;
  const pkg = slide.pkg;
  s.owned_drawables.push(ref(rootId));
  s.drawables_z_order.push(ref(rootId));
  pkg.addObjectReference(slide.slideId, rootId);
  // A table lives in the calculation engine's file; Keynote only loads it if
  // the slide's component says it refers to it.
  addExternalReference(pkg, pkg.component(componentIdOf(pkg, slide.slideId)), rootId);
  pkg.markChanged(slide.slideId);
  slide.touched();
}

export function removeFromSlide(slide: Slide, rootId: number): void {
  const s = slide.slide;
  const pkg = slide.pkg;
  for (const field of ["owned_drawables", "drawables_z_order", "infos_using_object_placeholder_geometry"]) {
    s[field] = (s[field] as Message[]).filter((r) => r.identifier !== rootId);
  }
  pkg.removeObjectReference(slide.slideId, rootId);
  removeExternalReference(pkg, pkg.component(componentIdOf(pkg, slide.slideId)), rootId);
  pkg.markChanged(slide.slideId);
  slide.touched();
}

// --- geometry -----------------------------------------------------------------

/** What every drawable's ``toJSON()`` has. */
export interface DrawableJSON {
  type: string;
  x: number;
  y: number;
  width: number;
  height: number;
  [key: string]: unknown;
}

/** Something drawn on a slide. Positions and sizes are in points from the slide's top left. */
export class Drawable {
  /** @internal */
  readonly pkg: Package;

  constructor(
    readonly slide: Slide,
    readonly identifier: number,
  ) {
    this.pkg = slide.pkg;
  }

  get kind(): string {
    return "drawable";
  }

  /** @internal */
  get archive(): Message {
    return this.pkg.get(this.identifier);
  }

  /** @internal The ``TSD.DrawableArchive`` part, which holds the frame. */
  get info(): Message {
    let a = this.archive;
    while (typeOf(a) !== "TSD.DrawableArchive") a = a.super;
    return a;
  }

  get position(): [number, number] {
    const p = sub(sub(this.info, "geometry"), "position");
    return [p.x, p.y];
  }

  set position(value: [number, number]) {
    const p = ensure(ensure(this.info, "geometry"), "position");
    [p.x, p.y] = value.map(Number);
    this.changed();
  }

  get size(): [number, number] {
    const s = sub(sub(this.info, "geometry"), "size");
    if (s.width === 0 && s.height === 0) {
      const natural = this.naturalSize();
      if (natural !== null) return natural;
    }
    return [s.width, s.height];
  }

  set size(value: [number, number]) {
    const [width, height] = value.map(Number);
    if (!(width > 0 && height > 0)) throw new Error("width and height must be more than 0");
    const s = ensure(ensure(this.info, "geometry"), "size");
    s.width = width;
    s.height = height;
    this.resized();
    this.changed();
  }

  /** @internal The size of a drawable, such as a text box that grows with its text, that has no size of its own. */
  naturalSize(): [number, number] | null {
    return null;
  }

  /** @internal */
  resized(): void {}

  /** @internal */
  changed(): void {
    this.pkg.markChanged(this.identifier);
    this.slide.touched();
  }

  toJSON(): DrawableJSON {
    const [x, y] = this.position;
    const [width, height] = this.size;
    return { type: this.kind, x, y, width, height };
  }

  /** @internal */
  beforeDelete(): void {}

  /** @internal Objects that belong to this drawable but that nothing in it refers to. */
  ownedElsewhere(_owned: number[]): number[] {
    return [];
  }
}

// --- shapes -------------------------------------------------------------------

/** Shape kinds for {@link Slide.addShape}. */
export const SHAPE_KINDS = [
  "rectangle",
  "rounded rectangle",
  "oval",
  "triangle",
  "diamond",
  "pentagon",
  "hexagon",
  "octagon",
  "star",
  "arrow",
  "double arrow",
  "plus",
] as const;
export type ShapeKind = (typeof SHAPE_KINDS)[number];

// Keynote draws its triangle and diamond as paths, other polygons from a number of sides.
const POLYGON_SIDES: Record<string, number> = { pentagon: 5, hexagon: 6, octagon: 8 };
const PATHS: Record<string, [number, number][]> = {
  rectangle: [[0, 0], [1, 0], [1, 1], [0, 1]],
  triangle: [[0.5, 0], [1, 1], [0, 1]],
  diamond: [[0, 0.5], [0.5, 1], [1, 0.5], [0.5, 0]],
};
const POINT_TYPES: Record<string, number> = { arrow: 1, "left arrow": 0, "double arrow": 10, star: 100, plus: 200 };
const SCALAR_TYPES = "TSD.ScalarPathSourceArchive.ScalarPathSourceType";

const size = (width: number, height: number): Message => create("TSP.Size", { width, height });
const point = (x: number, y: number): Message => create("TSP.Point", { x, y });

/** A ``TSD.PathSourceArchive`` for a shape of this kind, with Keynote's default proportions. */
function pathSource(kind: string, width: number, height: number): Message {
  const ps = create("TSD.PathSourceArchive", { horizontalFlip: false, verticalFlip: false });
  if (kind in PATHS || kind === "oval") {
    ps.bezier_path_source = create("TSD.BezierPathSourceArchive", { naturalSize: size(width, height), path: bezier(kind, width, height) });
  } else if (kind === "rounded rectangle") {
    ps.scalar_path_source = create("TSD.ScalarPathSourceArchive", {
      type: enumValue(SCALAR_TYPES, "kTSDRoundedRectangle"),
      scalar: Math.min(width, height) * 0.1,
      naturalSize: size(width, height),
      is_curve_continuous: true,
    });
  } else if (kind in POLYGON_SIDES) {
    ps.scalar_path_source = create("TSD.ScalarPathSourceArchive", {
      type: enumValue(SCALAR_TYPES, "kTSDRegularPolygon"),
      scalar: POLYGON_SIDES[kind],
      naturalSize: size(width, height),
      is_curve_continuous: false,
    });
  } else if (kind in POINT_TYPES) {
    let pt: Message;
    if (kind === "star") {
      pt = point(5, 0.382); // points, inner radius as a fraction of the outer
    } else if (kind === "plus") {
      pt = point(width / 3, height / 3);
    } else {
      // Keynote's defaults: the head's length in points, and the shaft's thickness as a fraction of the height.
      const head = kind === "arrow" ? 64.0 : 44.0;
      pt = point(Math.min(head, width / (kind === "arrow" ? 2 : 4)), 0.34);
    }
    ps.point_path_source = create("TSD.PointPathSourceArchive", { type: POINT_TYPES[kind], point: pt, naturalSize: size(width, height) });
  } else {
    throw new Error(`shape must be one of ${SHAPE_KINDS.join(", ")}, not ${JSON.stringify(kind)}`);
  }
  return ps;
}

function bezier(kind: string, w: number, h: number): Message {
  const elements: Message[] = [];
  const add = (type: number, ...points: [number, number][]) => {
    elements.push(create("TSP.Path.Element", { type, points: points.map(([x, y]) => point(x, y)) }));
  };
  const MOVE = 1, LINE = 2, CURVE = 4, CLOSE = 5;
  if (kind in PATHS) {
    // Closed, then a move back to the start, as Keynote writes them.
    const points = PATHS[kind].map(([x, y]): [number, number] => [x * w, y * h]);
    add(MOVE, points[0]);
    for (const pt of points.slice(1)) add(LINE, pt);
    add(CLOSE);
    add(MOVE, points[0]);
  } else {
    // An ellipse as four cubic curves.
    const k = (4 * (Math.SQRT2 - 1)) / 3;
    const rx = w / 2, ry = h / 2;
    add(MOVE, [w, ry]);
    add(CURVE, [w, ry + ry * k], [rx + rx * k, h], [rx, h]);
    add(CURVE, [rx - rx * k, h], [0, ry + ry * k], [0, ry]);
    add(CURVE, [0, ry - ry * k], [rx - rx * k, 0], [rx, 0]);
    add(CURVE, [rx + rx * k, 0], [w, ry - ry * k], [w, ry]);
    add(CLOSE);
  }
  return create("TSP.Path", { elements });
}

const round3 = (v: number) => Math.round(v * 1000) / 1000;

function kindOfPath(ps: Message): string {
  if (has(ps, "scalar_path_source")) {
    const s = ps.scalar_path_source;
    if (s.type === enumValue(SCALAR_TYPES, "kTSDRoundedRectangle")) return "rounded rectangle";
    if (s.type === enumValue(SCALAR_TYPES, "kTSDChevron")) return "chevron";
    const sides: Record<number, string> = { 3: "triangle", 4: "diamond", 5: "pentagon", 6: "hexagon", 8: "octagon" };
    return sides[Math.round(s.scalar)] ?? "polygon";
  }
  if (has(ps, "point_path_source")) {
    const name = Object.entries(POINT_TYPES).find(([, v]) => v === ps.point_path_source.type);
    return name ? name[0] : "shape";
  }
  if (has(ps, "bezier_path_source")) {
    const b = ps.bezier_path_source;
    const elements: Message[] = sub(b, "path").elements;
    const types = elements.map((e) => e.type as number);
    const count = (t: number) => types.filter((x) => x === t).length;
    if (count(4) === 4 && !types.includes(2)) return "oval";
    if (!types.includes(3) && !types.includes(4) && count(1) <= 2) {
      const n = sub(b, "naturalSize");
      const w = n.width || 1, h = n.height || 1;
      const outline: [number, number][] = [];
      for (const e of elements) {
        if (e.type === 5) break;
        for (const pt of e.points as Message[]) outline.push([round3(pt.x / w), round3(pt.y / h)]);
      }
      for (const [name, points] of Object.entries(PATHS)) if (samePolygon(outline, points)) return name;
    }
    return "custom";
  }
  if (has(ps, "callout_path_source")) return "callout";
  return "shape";
}

/** Whether ``outline`` visits the same corners as ``points``, from any start and in either direction. */
function samePolygon(outline: [number, number][], points: [number, number][]): boolean {
  if (outline.length !== points.length) return false;
  const n = points.length;
  for (let start = 0; start < n; start++) {
    for (const step of [1, -1]) {
      const ok = outline.every(([x, y], i) => {
        const [px, py] = points[(((start + step * i) % n) + n) % n];
        return Math.abs(x - px) < 0.01 && Math.abs(y - py) < 0.01;
      });
      if (ok) return true;
    }
  }
  return false;
}

function resizePath(ps: Message, width: number, height: number): void {
  if (has(ps, "bezier_path_source")) {
    const b = ps.bezier_path_source;
    const n = ensure(b, "naturalSize");
    const oldW = n.width || 1, oldH = n.height || 1;
    for (const e of sub(b, "path").elements as Message[]) {
      for (const pt of e.points as Message[]) {
        pt.x = (pt.x * width) / oldW;
        pt.y = (pt.y * height) / oldH;
      }
    }
    n.width = width;
    n.height = height;
  } else {
    for (const field of ["scalar_path_source", "point_path_source", "callout_path_source"]) {
      if (!has(ps, field)) continue;
      const s = ensure(ps[field], field === "callout_path_source" ? "natural_size" : "naturalSize");
      s.width = width;
      s.height = height;
    }
  }
}

/** A shape or text box. ``kind`` is e.g. ``"rectangle"``, ``"oval"`` or ``"text box"``. */
export class Shape extends Drawable {
  /** The ``TSD.ShapeArchive`` part. */
  private get shape(): Message {
    return this.archive.super;
  }

  get isTextBox(): boolean {
    return Boolean(this.archive.is_text_box);
  }

  override get kind(): string {
    return this.isTextBox ? "text box" : kindOfPath(sub(this.shape, "pathsource"));
  }

  override resized(): void {
    const [width, height] = this.size;
    resizePath(ensure(this.shape, "pathsource"), width, height);
    ensure(this.info, "geometry").flags = 3;
  }

  override naturalSize(): [number, number] | null {
    const ps = sub(this.shape, "pathsource");
    if (has(ps, "bezier_path_source")) {
      const n = sub(ps.bezier_path_source, "naturalSize");
      return [n.width, n.height];
    }
    return null;
  }

  /** Whether this is a text box in the theme's subtitle style, as ``Slide.addSubtitle`` makes. */
  get isSubtitle(): boolean {
    const a = this.archive;
    if (!this.isTextBox || !has(a, "owned_storage")) return false;
    const name = subtitleStyle(this.pkg);
    const entries = this.pkg.get(a.owned_storage.identifier).table_para_style?.entries ?? [];
    if (name === null || !entries.length) return false;
    const wanted = styleNamed(this.pkg, name);
    let styleId: number | undefined = entries[0].object?.identifier;
    while (styleId) {
      // the style or a variation of it
      if (styleId === wanted) return true;
      if (!this.pkg.has(styleId)) return false;
      let base: Message | undefined = this.pkg.get(styleId).super;
      while (base !== undefined && !has(base, "parent") && base.super !== undefined) base = base.super;
      if (base === undefined || !has(base, "parent")) return false;
      styleId = base.parent.identifier;
    }
    return false;
  }

  get textStorage(): Text | null {
    const a = this.archive;
    return has(a, "owned_storage") ? new Text(this.pkg, a.owned_storage.identifier) : null;
  }

  get text(): string {
    return this.textStorage?.toString() ?? "";
  }

  set text(value: string | Iterable<ParagraphInput>) {
    const t = this.textStorage;
    if (t === null) throw new Error("this shape has no text");
    t.setParagraphs(typeof value === "string" ? value.split("\n") : value);
    this.slide.touched();
  }

  /** The shape's style, made into a variation of the theme's style first if need be. */
  private ownStyle(): [number, Message] {
    const p = this.pkg;
    let styleId: number = this.shape.style.identifier;
    let style = p.get(styleId);
    if (!style.super.super.is_variation) {
      const themeStyle = styleId;
      [styleId, style] = addVariationStyle(p, themeStyle);
      this.shape.style.identifier = styleId;
      p.removeObjectReference(this.identifier, themeStyle);
      p.addObjectReference(this.identifier, styleId);
      addExternalReference(p, p.componentForFile(p.fileOf(this.identifier)), styleId);
      this.changed();
    }
    return [styleId, style];
  }

  /** The shape style property ``field``, following the style's parents. */
  private effective(field: string): Message | undefined {
    const p = this.pkg;
    let style = p.get(this.shape.style.identifier);
    for (;;) {
      const props = sub(style.super, "shape_properties");
      if (has(props, field)) return props[field];
      if (!has(style.super.super, "parent")) return undefined;
      style = p.deref(style.super.super.parent);
    }
  }

  /** Fill colour as ``"#rrggbb"``, or ``null`` for no fill, a gradient or an image. */
  get fill(): string | null {
    const fill = this.effective("fill");
    if (fill === undefined || !has(fill, "color")) return null;
    return colorHex(fill.color);
  }

  set fill(value: Color | null) {
    const [styleId, style] = this.ownStyle();
    const props = ensure(style.super, "shape_properties");
    if (!has(props, "fill")) style.super.override_count += 1;
    props.fill = value === null ? create("TSD.FillArchive") : create("TSD.FillArchive", { color: newColor(parseColor(value)) });
    this.pkg.markChanged(styleId);
    this.slide.touched();
  }

  override toJSON(): DrawableJSON {
    const d = super.toJSON();
    d.text = this.text;
    if (!this.isTextBox) d.fill = this.fill;
    return d;
  }
}

export interface ShapeOptions {
  text?: string | Iterable<ParagraphInput>;
  /** One of the theme's six shape styles, 0 to 5. */
  style?: number;
  fill?: Color;
  /** A paragraph style for the text by its name in the theme, e.g. ``"text-2-paragraphstyle-Subtitle"``. */
  paragraphStyle?: string;
}

export function addShape(slide: Slide, kind: string, x: number, y: number, width: number, height: number, options: ShapeOptions = {}): Shape {
  const p = slide.pkg;
  const isTextBox = kind === "text box";
  const style = options.style ?? 0;
  if (!isTextBox && !(SHAPE_KINDS as readonly string[]).includes(kind)) {
    throw new Error(`shape must be one of ${[...SHAPE_KINDS, "text box"].join(", ")}, not ${JSON.stringify(kind)}`);
  }
  if (!(width > 0 && height > 0)) throw new Error("width and height must be more than 0");
  if (!Number.isInteger(style) || style < 0 || style > 5) throw new Error("style must be 0 to 5, one of the theme's six shape styles");
  if (isTextBox && options.fill !== undefined) throw new Error("text boxes have no fill");

  const styleId = styleNamed(p, isTextBox ? "textbox-0-shapestyle" : `shape-${style}-shapestyle`);
  const paraStyle: number =
    options.paragraphStyle !== undefined
      ? styleNamed(p, options.paragraphStyle)
      : p.get(styleId).shape_properties.paragraph_style.identifier;
  const listStyle = styleNamed(p, "text-0-liststyle-None");
  const sheetId = stylesheetId(p);

  const slideFile = p.fileOf(slide.slideId);
  const component = p.componentForFile(slideFile);
  const [shapeId, captionId, titleId, storageId] = [0, 0, 0, 0].map(() => p.newIdentifier());

  const objectEntry = (identifier: number) =>
    create("TSWP.ObjectAttributeTable", { entries: [create("TSWP.ObjectAttributeTable.ObjectAttribute", { character_index: 0, object: ref(identifier) })] });
  const dataEntry = () =>
    create("TSWP.ParaDataAttributeTable", {
      entries: [create("TSWP.ParaDataAttributeTable.ParaDataAttribute", { character_index: 0, first: 0, second: 0 })],
    });
  const storage = create("TSWP.StorageArchive", {
    style_sheet: ref(sheetId),
    text: [""],
    table_para_style: objectEntry(paraStyle),
    table_para_data: dataEntry(),
    table_list_style: objectEntry(listStyle),
    in_document: true,
    table_para_starts: dataEntry(),
    table_para_bidi: dataEntry(),
    table_drop_cap_style: create("TSWP.ObjectAttributeTable", {
      entries: [create("TSWP.ObjectAttributeTable.ObjectAttribute", { character_index: 0 })],
    }),
  });

  const drawable = create("TSD.DrawableArchive", {
    geometry: create("TSD.GeometryArchive", { position: point(Number(x), Number(y)), size: size(Number(width), Number(height)), flags: 3, angle: 0 }),
    parent: ref(slide.slideId),
    exterior_text_wrap: create("TSD.ExteriorTextWrapArchive", { type: 4, direction: 2, fit_type: 1, margin: 12, alpha_threshold: 0.5, is_html_wrap: false }),
    locked: false,
    aspect_ratio_locked: false,
    title: ref(titleId),
    caption: ref(captionId),
    title_hidden: false,
    caption_hidden: false,
  });
  const info = create("TSWP.ShapeInfoArchive", {
    super: create("TSD.ShapeArchive", {
      super: drawable,
      style: ref(styleId),
      pathsource: pathSource(isTextBox ? "rectangle" : kind, Number(width), Number(height)),
      strokePatternOffsetDistance: 0,
    }),
    deprecated_storage: ref(storageId),
    owned_storage: ref(storageId),
    is_text_box: isTextBox,
  });

  const caption = () => create("TSD.StandinCaptionArchive");
  p.addSegment(slideFile, { header: makeHeader(shapeId, SHAPE_INFO[0], SHAPE_INFO[1], [captionId, titleId, styleId, storageId]), objects: [info] });
  p.addSegment(slideFile, { header: makeHeader(captionId, CAPTION[0], CAPTION[1]), objects: [caption()] });
  p.addSegment(slideFile, { header: makeHeader(titleId, CAPTION[0], CAPTION[1]), objects: [caption()] });
  p.addSegment(slideFile, { header: makeHeader(storageId, STORAGE[0], STORAGE[1], [paraStyle, listStyle]), objects: [storage] });
  for (const identifier of [shapeId, captionId, titleId, storageId]) addUuid(component, identifier);
  for (const target of [styleId, paraStyle, listStyle]) addExternalReference(p, component, target);
  p.markChanged(METADATA_ID);

  placeOnSlide(slide, shapeId);
  const shape = new Shape(slide, shapeId);
  if (options.text !== undefined) shape.text = options.text;
  if (options.fill !== undefined) shape.fill = options.fill;
  return shape;
}

/** Drop a component's UUID entries for objects that no longer exist. */
export function forgetObjects(component: Message, ids: Set<number>): void {
  component.object_uuid_map_entries = (component.object_uuid_map_entries as Message[]).filter((e) => !ids.has(e.identifier));
}
