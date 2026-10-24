/**
 * Images on slides: read, add, replace and remove them.
 *
 * An image is a ``TSD.ImageArchive`` in the slide's component file, listed in
 * ``KN.SlideArchive.owned_drawables`` and ``drawables_z_order``. Its pixels are
 * a data file in ``Data/``: the image points at it with a ``TSP.DataReference``,
 * ``TSP.PackageMetadata.datas`` holds a ``TSP.DataInfo`` for it (file name,
 * SHA-1 digest, length), and both the image's archive header and the slide's
 * component list which data each object uses.
 *
 * A layout's media placeholder is an image tagged ``"Media"`` (or
 * ``"Media-1"`` and so on) in ``KN.SlideArchive.sage_tag_to_info_map``. Until
 * it is replaced, it shows one of the theme's sample photos, which isn't stored
 * in the file: its ``DataInfo`` has a ``document_resource_locator`` instead of a
 * file name. A placeholder crops its photo with a ``TSD.MaskArchive``, a child
 * of the image whose geometry is relative to the image. Filling one keeps the
 * mask where it is and scales the new picture to cover it.
 */

import { removeBuildsFor } from "./builds.js";
import type { Slide } from "./document.js";
import { METADATA_ID, addUuid, makeHeader, type Package } from "./package.js";
import { clear, create, ensure, has, sub, typeOf, type Message } from "./protobuf.js";
import { sha1 } from "./sha1.js";

const IMAGE_TYPE = 3005; // TSD.ImageArchive
const MESSAGE_VERSION = [1, 0, 5];
const DEFAULT_STYLE = "image-0-imageStyle";
const IMAGE_ATTRIBUTES = "TSD.ImageDataAttributes.image_data_attributes";

/** Image bytes: PNG, JPEG or GIF. */
export type ImageSource = Uint8Array | ArrayBuffer;

/**
 * One image on a slide.
 *
 * ``position`` and ``size`` are the part you see, in points from the slide's
 * top left, so for a cropped photo they are the crop, not the whole picture.
 * ``data`` is ``null`` for a placeholder still showing the theme's sample
 * photo, which Keynote keeps outside the file.
 */
export interface Image {
  identifier: number;
  position: [number, number];
  size: [number, number];
  pixelSize: [number, number];
  /** Accessibility description, Markdown's alt text. */
  description: string;
  /** The layout's tag, e.g. ``"Media"``, if this is a media placeholder. */
  placeholder: string | null;
  /** The file's name in ``Data/``. */
  filename: string | null;
  /** The name it was added under, e.g. ``"robot.png"``. */
  name: string | null;
  data: Uint8Array | null;
  /** True for a media placeholder that still shows the theme's sample photo. */
  isSample: boolean;
}

// --- image files ---------------------------------------------------------------

/** ``[format, width, height]`` of PNG, JPEG or GIF data, read from its header. */
export function imageFormat(data: Uint8Array): ["png" | "jpeg" | "gif", number, number] {
  const view = new DataView(data.buffer, data.byteOffset, data.byteLength);
  const ascii = (start: number, end: number) => String.fromCharCode(...data.subarray(start, end));
  if (data.length >= 24 && data[0] === 0x89 && ascii(1, 8) === "PNG\r\n\x1a\n" && ascii(12, 16) === "IHDR") {
    return ["png", view.getUint32(16), view.getUint32(20)];
  }
  if (data.length >= 10 && (ascii(0, 6) === "GIF87a" || ascii(0, 6) === "GIF89a")) {
    return ["gif", view.getUint16(6, true), view.getUint16(8, true)];
  }
  if (data[0] === 0xff && data[1] === 0xd8) {
    let i = 2;
    while (i + 9 < data.length) {
      if (data[i] !== 0xff) {
        i += 1;
        continue;
      }
      const marker = data[i + 1];
      if (marker === 0xd8 || marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7) || marker === 0xff) {
        i += marker === 0xff ? 1 : 2;
        continue;
      }
      const length = view.getUint16(i + 2);
      // Start-of-frame markers, apart from DHT (C4), JPG (C8) and DAC (CC).
      if (marker >= 0xc0 && marker <= 0xcf && ![0xc4, 0xc8, 0xcc].includes(marker)) {
        return ["jpeg", view.getUint16(i + 7), view.getUint16(i + 5)];
      }
      i += 2 + length;
    }
  }
  throw new Error("unsupported image: keynotejs can add PNG, JPEG and GIF files");
}

function bytesOf(source: ImageSource): Uint8Array {
  if (source instanceof Uint8Array) return source;
  if (source instanceof ArrayBuffer) return new Uint8Array(source);
  throw new TypeError("an image must be a Uint8Array or ArrayBuffer of PNG, JPEG or GIF data");
}

function fileNames(name: string, fmt: string, dataId: number): [string, string] {
  const base = name.split(/[\\/]/).pop() ?? "";
  const dot = base.lastIndexOf(".");
  let stem = dot > 0 ? base.slice(0, dot) : base;
  stem = stem.replace(/[^\p{L}\p{N}_.-]+/gu, "-").replace(/^-+|-+$/g, "") || "image";
  return [`${stem}.${fmt}`, `${stem}-${dataId}.${fmt}`];
}

function sameBytes(a: Uint8Array, b: Uint8Array): boolean {
  return a.length === b.length && a.every((x, i) => x === b[i]);
}

/** Store ``data`` in ``Data/`` and return its data identifier. The same bytes are stored once. */
export function addData(pkg: Package, data: Uint8Array, name: string, fmt: string, pixelSize: [number, number]): number {
  const digest = sha1(data);
  const meta = pkg.metadata;
  for (const info of meta.datas as Message[]) {
    if (sameBytes(info.digest, digest) && info.file_name && pkg.hasFile(`Data/${info.file_name}`)) return info.identifier;
  }
  const dataId = pkg.newIdentifier();
  const [preferred, fileName] = fileNames(name, fmt, dataId);
  meta.datas.push(
    create("TSP.DataInfo", {
      identifier: dataId,
      digest,
      preferred_file_name: preferred,
      file_name: fileName,
      materialized_length: data.length,
      attributes: create("TSP.DataAttributes", {
        [IMAGE_ATTRIBUTES]: create("TSD.ImageDataAttributes", {
          pixel_size: create("TSP.Size", { width: pixelSize[0], height: pixelSize[1] }),
          should_be_interpreted_as_generic_if_untagged: false,
        }),
      }),
    }),
  );
  pkg.writeFile(`Data/${fileName}`, data);
  pkg.markChanged(METADATA_ID);
  return dataId;
}

function dataInfo(pkg: Package, dataId: number): Message | undefined {
  return (pkg.metadata.datas as Message[]).find((info) => info.identifier === dataId);
}

function useData(pkg: Package, component: Message, objectId: number, dataId: number): void {
  const refs: number[] = pkg.segment(objectId).header.message_infos[0].data_references;
  if (!refs.includes(dataId)) refs.push(dataId);
  const entry = () => create("TSP.ComponentDataReference.ObjectReference", { object_identifier: objectId, count: 1 });
  const ref = (component.data_references as Message[]).find((r) => r.data_identifier === dataId);
  if (ref) {
    if (!(ref.object_reference_list as Message[]).some((o) => o.object_identifier === objectId)) ref.object_reference_list.push(entry());
  } else {
    component.data_references.push(create("TSP.ComponentDataReference", { data_identifier: dataId, object_reference_list: [entry()] }));
  }
  pkg.markChanged(objectId);
  pkg.markChanged(METADATA_ID);
}

/** Stop ``objectId`` using these data, and delete any data nothing uses any more. */
function dropData(pkg: Package, component: Message, objectId: number, dataIds: number[]): void {
  const gone = new Set(dataIds);
  if (pkg.has(objectId)) {
    const info = pkg.segment(objectId).header.message_infos[0];
    info.data_references = (info.data_references as number[]).filter((d) => !gone.has(d));
    pkg.markChanged(objectId);
  }
  for (const ref of component.data_references as Message[]) {
    if (!gone.has(ref.data_identifier)) continue;
    ref.object_reference_list = (ref.object_reference_list as Message[]).filter((o) => o.object_identifier !== objectId);
  }
  component.data_references = (component.data_references as Message[]).filter((r) => r.object_reference_list.length > 0);
  const meta = pkg.metadata;
  const inUse = new Set<number>();
  for (const c of meta.components as Message[]) for (const r of c.data_references as Message[]) inUse.add(r.data_identifier);
  let described = new Set<number>();
  if (has(meta, "data_metadata_map") && pkg.has(meta.data_metadata_map.identifier)) {
    described = new Set((pkg.deref(meta.data_metadata_map).data_metadata_entries as Message[]).map((e) => e.data_identifier));
  }
  for (const dataId of dataIds) {
    const info = dataInfo(pkg, dataId);
    // Only delete files keynotejs could have added; theme resources stay.
    if (inUse.has(dataId) || info === undefined || !info.file_name || described.has(dataId)) continue;
    pkg.removeFile(`Data/${info.file_name}`);
    meta.datas = (meta.datas as Message[]).filter((i) => i.identifier !== dataId);
  }
  pkg.markChanged(METADATA_ID);
}

// --- reading -------------------------------------------------------------------

function placeholderTags(slide: Slide): Map<number, string> {
  const tags = new Map<number, string>();
  for (const e of slide.slide.sage_tag_to_info_map as Message[]) {
    if (e.tag.startsWith("Media")) tags.set(e.info.identifier, e.tag);
  }
  return tags;
}

function frame(pkg: Package, image: Message): [[number, number], [number, number]] {
  const g = sub(image.super, "geometry");
  const pos = sub(g, "position");
  if (has(image, "mask") && pkg.has(image.mask.identifier)) {
    const m = sub(pkg.deref(image.mask).super, "geometry");
    const mp = sub(m, "position");
    const ms = sub(m, "size");
    return [[pos.x + mp.x, pos.y + mp.y], [ms.width, ms.height]];
  }
  const s = sub(g, "size");
  return [[pos.x, pos.y], [s.width, s.height]];
}

function imageIds(slide: Slide): number[] {
  const p = slide.pkg;
  return (slide.slide.drawables_z_order as Message[])
    .map((r) => r.identifier as number)
    .filter((i) => p.has(i) && isImage(p, i));
}

function isImage(pkg: Package, identifier: number): boolean {
  try {
    return typeOf(pkg.get(identifier)) === "TSD.ImageArchive";
  } catch {
    return false;
  }
}

export function readImage(slide: Slide, identifier: number): Image {
  const p = slide.pkg;
  const obj = p.get(identifier);
  const [position, size] = frame(p, obj);
  const info = has(obj, "data") ? dataInfo(p, obj.data.identifier) : undefined;
  const name = info !== undefined && info.file_name ? `Data/${info.file_name}` : null;
  const data = name !== null && p.hasFile(name) ? p.readFile(name) : null;
  const natural = sub(obj, "naturalSize");
  return {
    identifier,
    position,
    size,
    pixelSize: [Math.trunc(natural.width), Math.trunc(natural.height)],
    description: sub(obj, "super").accessibility_description,
    placeholder: placeholderTags(slide).get(identifier) ?? null,
    filename: data !== null ? info!.file_name : null,
    name: data !== null ? info!.preferred_file_name || info!.file_name : null,
    data,
    isSample: data === null,
  };
}

/** The slide's images, back to front. */
export function readImages(slide: Slide): Image[] {
  return imageIds(slide).map((i) => readImage(slide, i));
}

/** The slide's media placeholders in reading order, left to right and top to bottom. */
export function placeholders(slide: Slide): Image[] {
  const rows: Image[][] = [];
  const sorted = readImages(slide)
    .filter((i) => i.placeholder !== null)
    .sort((a, b) => a.position[1] - b.position[1]);
  for (const image of sorted) {
    // Tops within 20 points of each other count as one row.
    const last = rows[rows.length - 1];
    if (last && image.position[1] - last[0].position[1] <= 20) last.push(image);
    else rows.push([image]);
  }
  return rows.flatMap((row) => row.sort((a, b) => a.position[0] - b.position[0]));
}

// --- changing ------------------------------------------------------------------

/** An image to change: an {@link Image}, its index in ``slide.images``, its identifier, or a placeholder tag such as ``"Media"``. */
export type ImageTarget = Image | number | string;

function resolve(slide: Slide, target: ImageTarget): number {
  const ids = imageIds(slide);
  if (typeof target === "object" && target !== null) target = target.identifier;
  if (typeof target === "string") {
    for (const [identifier, tag] of placeholderTags(slide)) if (tag === target && ids.includes(identifier)) return identifier;
    throw new Error(`slide ${slide.index} has no media placeholder ${JSON.stringify(target)}`);
  }
  if (typeof target === "number" && Number.isInteger(target)) {
    if (ids.includes(target)) return target;
    if (target >= -ids.length && target < ids.length) return ids[target < 0 ? target + ids.length : target];
  }
  throw new Error(`slide ${slide.index} has no image ${JSON.stringify(target)}`);
}

function defaultStyle(pkg: Package): number {
  for (const [identifier, obj] of pkg.objects("TSD.MediaStyleArchive")) {
    if (obj.super.name === "" && obj.super.style_identifier === DEFAULT_STYLE) return identifier;
  }
  for (const [, obj] of pkg.objects("TSD.ImageArchive")) {
    if (has(obj, "style")) return obj.style.identifier;
  }
  throw new Error("this presentation's theme has no image style to use");
}

/** Record that ``component`` refers to ``target``, an object in another component. */
function referToExternal(pkg: Package, component: Message, target: number): void {
  const other = pkg.componentForFile(pkg.fileOf(target));
  if (other.identifier === component.identifier) return;
  for (const e of component.external_references as Message[]) {
    if (e.component_identifier === other.identifier && e.object_identifier === target) return;
  }
  component.external_references.push(create("TSP.ComponentExternalReference", { component_identifier: other.identifier, object_identifier: target }));
  pkg.markChanged(METADATA_ID);
}

function fit(pixelSize: [number, number], box: [number, number], cover: boolean): [number, number] {
  const [w, h] = pixelSize;
  const scale = (cover ? Math.max : Math.min)(box[0] / w, box[1] / h);
  return [w * scale, h * scale];
}

function sizeFor(slide: Slide, pixelSize: [number, number], size?: [number | null, number | null]): [number, number] {
  const [w, h] = pixelSize;
  if (size && size[0] != null && size[1] != null) return [Number(size[0]), Number(size[1])];
  if (size && size[0] != null) return [Number(size[0]), (size[0] * h) / w];
  if (size && size[1] != null) return [(size[1] * w) / h, Number(size[1])];
  const { width: slideW, height: slideH } = slide.presentation.size;
  if (w <= slideW * 0.8 && h <= slideH * 0.8) return [w, h];
  return fit(pixelSize, [slideW * 0.8, slideH * 0.8], false);
}

export interface AddImageOptions {
  /** Top left, in points. Centred if not given. */
  position?: [number, number];
  /** Width and height in points; give one as ``null`` to keep the picture's shape. */
  size?: [number | null, number | null];
  /** The accessibility description (alt text). */
  description?: string;
  /** ``false`` to put the image on top even when there's a free placeholder, or a placeholder's tag such as ``"Media-2"``. */
  placeholder?: boolean | string;
  /** The file name to store the bytes under, e.g. ``"robot.png"``. */
  name?: string;
}

export function addImage(slide: Slide, source: ImageSource, options: AddImageOptions = {}): Image {
  const data = bytesOf(source);
  const name = options.name ?? "image";
  const [fmt, w, h] = imageFormat(data);
  let placeholder = options.placeholder;
  if (placeholder === undefined && options.position === undefined && options.size === undefined) {
    // Fill the first media placeholder still showing the theme's sample.
    const free = placeholders(slide).filter((i) => i.isSample);
    placeholder = free.length ? free[0].placeholder! : false;
  }
  if (placeholder) {
    if (placeholder === true) {
      const free = placeholders(slide).filter((i) => i.isSample);
      if (!free.length) throw new Error(`slide ${slide.index} has no empty media placeholder`);
      placeholder = free[0].placeholder!;
    }
    return replace(slide, resolve(slide, placeholder), data, name, fmt, [w, h], options.description);
  }

  const p = slide.pkg;
  const s = slide.slide;
  const slideFile = p.fileOf(slide.slideId);
  const component = p.componentForFile(slideFile);
  const [width, height] = sizeFor(slide, [w, h], options.size);
  let position = options.position;
  if (position === undefined) {
    const { width: slideW, height: slideH } = slide.presentation.size;
    position = [(slideW - width) / 2, (slideH - height) / 2];
  }
  const styleId = defaultStyle(p);
  const dataId = addData(p, data, name, fmt, [w, h]);

  const imageId = p.newIdentifier();
  const image = create("TSD.ImageArchive", {
    super: create("TSD.DrawableArchive", {
      geometry: create("TSD.GeometryArchive", {
        position: create("TSP.Point", { x: Number(position[0]), y: Number(position[1]) }),
        size: create("TSP.Size", { width, height }),
        flags: 3,
        angle: 0.0,
      }),
      parent: create("TSP.Reference", { identifier: slide.slideId }),
      exterior_text_wrap: create("TSD.ExteriorTextWrapArchive", { type: 4, direction: 2, fit_type: 1, margin: 12.0, alpha_threshold: 0.5, is_html_wrap: false }),
      locked: false,
      aspect_ratio_locked: true,
      accessibility_description: options.description ?? "",
    }),
    style: create("TSP.Reference", { identifier: styleId }),
    originalSize: create("TSP.Size", { width, height }),
    flags: 1,
    naturalSize: create("TSP.Size", { width: w, height: h }),
    data: create("TSP.DataReference", { identifier: dataId }),
    interpretsUntaggedImageDataAsGeneric: false,
  });
  p.addSegment(slideFile, { header: makeHeader(imageId, IMAGE_TYPE, MESSAGE_VERSION, [styleId]), objects: [image] });
  addUuid(component, imageId);
  useData(p, component, imageId, dataId);
  referToExternal(p, component, styleId);

  s.owned_drawables.push(create("TSP.Reference", { identifier: imageId }));
  s.drawables_z_order.push(create("TSP.Reference", { identifier: imageId }));
  p.addObjectReference(slide.slideId, imageId);
  p.markChanged(slide.slideId);
  slide.touched();
  return readImage(slide, imageId);
}

export function replaceImage(slide: Slide, target: ImageTarget, source: ImageSource, options: { description?: string; name?: string } = {}): Image {
  const data = bytesOf(source);
  const [fmt, w, h] = imageFormat(data);
  return replace(slide, resolve(slide, target), data, options.name ?? "image", fmt, [w, h], options.description);
}

function replace(
  slide: Slide,
  imageId: number,
  data: Uint8Array,
  name: string,
  fmt: string,
  pixelSize: [number, number],
  description: string | undefined,
): Image {
  const p = slide.pkg;
  const component = p.componentForFile(p.fileOf(slide.slideId));
  const image = p.get(imageId);
  const [[vx, vy], [vw, vh]] = frame(p, image);
  const oldData = [...(p.segment(imageId).header.message_infos[0].data_references as number[])];
  let width: number, height: number, x: number, y: number;
  if (has(image, "mask") && p.has(image.mask.identifier)) {
    // Cover the crop, centred, and move the mask so the crop stays put.
    [width, height] = fit(pixelSize, [vw, vh], true);
    [x, y] = [vx + (vw - width) / 2, vy + (vh - height) / 2];
    const mask = p.deref(image.mask);
    const mp = ensure(ensure(mask.super, "geometry"), "position");
    mp.x = vx - x;
    mp.y = vy - y;
    p.markChanged(image.mask.identifier);
  } else {
    [width, height] = fit(pixelSize, [vw, vh], false);
    [x, y] = [vx + (vw - width) / 2, vy + (vh - height) / 2];
  }
  const g = ensure(image.super, "geometry");
  Object.assign(ensure(g, "position"), { x, y });
  Object.assign(ensure(g, "size"), { width, height });
  Object.assign(ensure(image, "originalSize"), { width, height });
  Object.assign(ensure(image, "naturalSize"), { width: pixelSize[0], height: pixelSize[1] });
  for (const f of [
    "thumbnailData",
    "originalData",
    "originalSVGData",
    "instantAlphaPath",
    "imageAdjustments",
    "enhancedImageData",
    "adjustedImageData",
    "thumbnailAdjustedImageData",
    "traced_path",
    "attribution",
    "background_removed",
  ]) {
    clear(image, f);
  }
  // The old description was of the old picture, as with the theme's sample photos.
  image.super.accessibility_description = description ?? "";
  const dataId = addData(p, data, name, fmt, pixelSize);
  image.data = create("TSP.DataReference", { identifier: dataId });
  dropData(p, component, imageId, oldData.filter((d) => d !== dataId));
  useData(p, component, imageId, dataId);
  p.markChanged(imageId);
  slide.touched();
  return readImage(slide, imageId);
}

export function removeImage(slide: Slide, target: ImageTarget): void {
  const p = slide.pkg;
  const s = slide.slide;
  const imageId = resolve(slide, target);
  const image = p.get(imageId);
  const component = p.componentForFile(p.fileOf(slide.slideId));
  removeBuildsFor(slide, imageId);

  const dataIds = [...(p.segment(imageId).header.message_infos[0].data_references as number[])];
  dropData(p, component, imageId, dataIds);
  const gone = new Set([imageId]);
  if (has(image, "mask") && p.has(image.mask.identifier)) gone.add(image.mask.identifier);
  for (const f of ["title", "caption"]) {
    if (has(image.super, f) && p.has(image.super[f].identifier)) gone.add(image.super[f].identifier);
  }
  const slideFile = p.fileOf(slide.slideId);
  for (const identifier of gone) if (p.fileOf(identifier) === slideFile) p.removeSegment(identifier);
  for (const field of ["owned_drawables", "drawables_z_order"]) {
    s[field] = (s[field] as Message[]).filter((r) => r.identifier !== imageId);
  }
  s.sage_tag_to_info_map = (s.sage_tag_to_info_map as Message[]).filter((e) => e.info.identifier !== imageId);
  p.removeObjectReference(slide.slideId, imageId);
  component.object_uuid_map_entries = (component.object_uuid_map_entries as Message[]).filter((e) => !gone.has(e.identifier));
  p.markChanged(slide.slideId);
  p.markChanged(METADATA_ID);
  slide.touched();
}
