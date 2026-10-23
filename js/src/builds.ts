/**
 * Build animations: how a slide's title, body or shapes appear on click.
 *
 * A slide lists its builds in ``KN.SlideArchive.builds``, one
 * ``KN.BuildArchive`` per animated object. The order they play in is
 * ``KN.SlideArchive.buildChunks``: one ``KN.BuildChunkArchive`` per click
 * ("event"), so a body built by paragraph has a chunk per paragraph. Chunks
 * name their build by a UUID, which is also recorded as the build's identity
 * in the slide's component.
 *
 * The field values written here are the ones Keynote 14.5 writes for a
 * default Dissolve or Move In build.
 */

import type { Slide } from "./document.js";
import { METADATA_ID, int64, makeHeader, newUuidParts } from "./package.js";
import { clear, create, enumValue, has, sub, type Message } from "./protobuf.js";

const BUILD_TYPE = 8; // KN.BuildArchive
const CHUNK_TYPE = 153; // KN.BuildChunkArchive
const MESSAGE_VERSION = [1, 0, 5];
const STALE_CACHE = 0xffffffff; // tells Keynote to recount builds when it opens the file

/** Delivery names you can pass, and what Keynote calls them. */
export const DELIVERY_NAMES: Record<string, string> = {
  "all at once": "All at Once",
  "by paragraph": "By Paragraph",
  "by bullet": "By Paragraph",
};
const KINDS: Record<string, string> = { in: "In", out: "Out" };
const ATTRS = "KN.BuildAttributesArchive.BuildAttributes";

/** One build on a slide. */
export interface Build {
  /** ``"title"``, ``"body"``, or the identifier of another drawable. */
  target: "title" | "body" | number;
  kind: "in" | "out";
  /** e.g. ``"dissolve"``, ``"move in"``. */
  effect: string;
  /** Keynote's delivery name, e.g. ``"All at Once"``, ``"By Paragraph"``. */
  delivery: string;
  duration: number;
  /** Clicks this build takes. */
  steps: number;
  /** Keynote's own effect id, e.g. ``"apple:dissolve character"``. */
  effectId: string;
}

/** What to build: ``"title"``, ``"body"``, a drawable (shape, image, table or chart) or its identifier. */
export type BuildTarget = "title" | "body" | number | { identifier: number };

export interface BuildOptions {
  /** A build effect such as ``"dissolve"`` or ``"move in"``, or Keynote's id such as ``"apple:dissolve character"``. Defaults to dissolve. */
  effect?: string;
  /** ``"all at once"`` or ``"by bullet"`` (also ``"by paragraph"``). Defaults to by bullet for a body with several paragraphs. */
  delivery?: string;
  /** Seconds. Defaults to 1. */
  duration?: number;
  /** ``"in"`` (the default) or ``"out"``. */
  kind?: "in" | "out";
}

function effectIdOf(name: string): string {
  if (name.includes(":")) return name;
  return "apple:" + name.trim().toLowerCase().replace(/[_-]/g, " ") + " character";
}

function effectNameOf(effectId: string): string {
  const name = effectId.includes(":") ? effectId.slice(effectId.indexOf(":") + 1) : effectId;
  return name.endsWith(" character") ? name.slice(0, -" character".length) : name;
}

function targetName(slide: Slide, drawableId: number): "title" | "body" | number {
  const s = slide.slide;
  if (has(s, "titlePlaceholder") && s.titlePlaceholder.identifier === drawableId) return "title";
  if (has(s, "bodyPlaceholder") && s.bodyPlaceholder.identifier === drawableId) return "body";
  return drawableId;
}

export function readBuilds(slide: Slide): Build[] {
  const p = slide.pkg;
  // Play order is the order of the chunks. Keynote doesn't keep ``builds``
  // in that order when it saves, so sort by each build's first chunk.
  const steps = new Map<number, number>();
  for (const ref of slide.slide.buildChunks as Message[]) {
    const buildId: number = p.deref(ref).build.identifier;
    steps.set(buildId, (steps.get(buildId) ?? 0) + 1);
  }
  const first = new Map([...steps.keys()].map((id, i) => [id, i]));
  const refs = [...(slide.slide.builds as Message[])].sort(
    (a, b) => (first.get(a.identifier) ?? first.size) - (first.get(b.identifier) ?? first.size),
  );
  return refs.map((ref) => {
    const b = p.deref(ref);
    const a = sub(sub(b, "attributes"), "animationAttributes");
    return {
      target: targetName(slide, b.drawable.identifier),
      kind: a.animation_type.toLowerCase(),
      effect: effectNameOf(a.effect),
      delivery: b.delivery,
      duration: a.duration,
      steps: steps.get(ref.identifier) ?? 0,
      effectId: a.effect,
    };
  });
}

function resolveTarget(slide: Slide, target: BuildTarget): number {
  const s = slide.slide;
  const shown = new Set((s.drawables_z_order as Message[]).map((r) => r.identifier));
  if (target === "title" || target === "body") {
    const field = target === "title" ? "titlePlaceholder" : "bodyPlaceholder";
    if (!has(s, field) || !shown.has(s[field].identifier)) {
      throw new Error(`the "${slide.layout}" layout doesn't show a ${target} on slide ${slide.index}`);
    }
    return s[field].identifier;
  }
  const id = typeof target === "object" && target !== null ? target.identifier : target;
  if (typeof id === "number" && shown.has(id)) return id;
  throw new Error(`build target must be "title", "body" or a drawable on the slide, not ${JSON.stringify(target)}`);
}

export function addBuild(slide: Slide, target: BuildTarget = "body", options: BuildOptions = {}): Build {
  const p = slide.pkg;
  const s = slide.slide;
  const drawableId = resolveTarget(slide, target);
  const kind = options.kind ?? "in";
  const duration = options.duration ?? 1.0;
  if (!(kind in KINDS)) throw new Error(`kind must be "in" or "out", not ${JSON.stringify(kind)}`);
  const isText = target === "title" || target === "body";
  const isBody = target === "body";
  let delivery = options.delivery;
  if (delivery === undefined) delivery = isBody && slide.paragraphs.length > 1 ? "by paragraph" : "all at once";
  const deliveryName = DELIVERY_NAMES[delivery.toLowerCase()];
  if (deliveryName === undefined) {
    throw new Error(`delivery must be one of ${Object.keys(DELIVERY_NAMES).sort().join(", ")}, not ${JSON.stringify(delivery)}`);
  }
  let steps = 1;
  if (deliveryName === "By Paragraph") {
    if (!isText) throw new Error("only text placeholders can be built by paragraph");
    const text = isBody ? slide.bodyText! : slide.titleText!;
    steps = Math.max(1, text.paragraphs.filter((para) => para.text.trim()).length);
  }

  const slideFile = p.fileOf(slide.slideId);
  const component = p.componentForFile(slideFile);
  const [lowerBig, upperBig] = newUuidParts();
  const lower = int64(lowerBig as bigint);
  const upper = int64(upperBig as bigint);

  const buildId = p.newIdentifier();
  const effect = effectIdOf(options.effect ?? "dissolve");
  const a = create("KN.AnimationAttributesArchive", {
    animation_type: KINDS[kind],
    effect,
    duration: Number(duration),
    delay: 0.0,
    random_number_seed: 1 + Math.floor(Math.random() * (2 ** 31 - 1)),
    writing_direction_is_rtl: false,
  });
  const attrs = create("KN.BuildAttributesArchive", {
    eventTrigger: 1,
    ChartRotation3D: 60.0,
    animationAttributes: a,
    custom_textDelivery: enumValue(`${ATTRS}TextDelivery`, "kTextDeliveryByObject"),
    custom_deliveryOption: enumValue(`${ATTRS}DeliveryOption`, "kDeliveryOptionForward"),
  });
  if (effect === "apple:move in character") {
    // Keynote's defaults for Move In.
    attrs.custom_bounce = true;
    attrs.custom_deliveryOption = enumValue(`${ATTRS}DeliveryOption`, "kDeliveryOptionBackward");
  }
  const build = create("KN.BuildArchive", {
    drawable: create("TSP.Reference", { identifier: drawableId }),
    delivery: deliveryName,
    duration: 0.0,
    attributes: attrs,
    chunk_id_seed: steps,
  });
  p.addSegment(slideFile, { header: makeHeader(buildId, BUILD_TYPE, MESSAGE_VERSION), objects: [build] });
  component.object_uuid_map_entries.push(
    create("TSP.ObjectUUIDMapEntry", { identifier: buildId, uuid: create("TSP.UUID", { lower, upper }) }),
  );

  s.builds.push(create("TSP.Reference", { identifier: buildId }));
  p.addObjectReference(slide.slideId, buildId);
  for (let step = 1; step <= steps; step++) {
    const chunkId = p.newIdentifier();
    const chunk = create("KN.BuildChunkArchive", {
      build: create("TSP.Reference", { identifier: buildId }),
      delay: 0.0,
      duration: Number(duration),
      automatic: false,
      referent: true,
      build_chunk_identifier: create("KN.BuildChunkIdentifierArchive", {
        build_id: create("TSP.UUID", { lower, upper }),
        build_chunk_id: step,
      }),
      build_id: create("TSP.UUID", { lower, upper }),
    });
    p.addSegment(slideFile, { header: makeHeader(chunkId, CHUNK_TYPE, MESSAGE_VERSION), objects: [chunk] });
    s.buildChunks.push(create("TSP.Reference", { identifier: chunkId }));
    p.addObjectReference(slide.slideId, chunkId);
  }

  buildsChanged(slide);
  const all = readBuilds(slide);
  return all[all.length - 1];
}

function removeIds(slide: Slide, gone: Set<number>): void {
  const p = slide.pkg;
  const s = slide.slide;
  for (const identifier of gone) {
    p.removeSegment(identifier);
    p.removeObjectReference(slide.slideId, identifier);
  }
  s.builds = (s.builds as Message[]).filter((r) => !gone.has(r.identifier));
  s.buildChunks = (s.buildChunks as Message[]).filter((r) => !gone.has(r.identifier));
  const component = p.componentForFile(p.fileOf(slide.slideId));
  component.object_uuid_map_entries = (component.object_uuid_map_entries as Message[]).filter((e) => !gone.has(e.identifier));
  buildsChanged(slide);
}

export function clearBuilds(slide: Slide): void {
  const s = slide.slide;
  const gone = new Set<number>([...(s.builds as Message[]), ...(s.buildChunks as Message[])].map((r) => r.identifier));
  if (gone.size) removeIds(slide, gone);
}

/** Remove the builds that animate one drawable, for when it is deleted. */
export function removeBuildsFor(slide: Slide, drawableId: number): void {
  const p = slide.pkg;
  const s = slide.slide;
  const builds = new Set((s.builds as Message[]).filter((r) => p.deref(r).drawable.identifier === drawableId).map((r) => r.identifier));
  if (!builds.size) return;
  const chunks = (s.buildChunks as Message[]).filter((r) => builds.has(p.deref(r).build.identifier)).map((r) => r.identifier);
  removeIds(slide, new Set([...builds, ...chunks]));
}

function buildsChanged(slide: Slide): void {
  const p = slide.pkg;
  const node = slide.node;
  node.build_event_count = slide.slide.buildChunks.length;
  node.build_event_count_cache_version = STALE_CACHE;
  node.has_explicit_builds_cache_version = STALE_CACHE;
  clear(node, "has_explicit_builds");
  node.thumbnailsAreDirty = true;
  p.markChanged(slide.nodeId);
  p.markChanged(slide.slideId);
  p.markChanged(METADATA_ID);
}
