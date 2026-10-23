/**
 * The theme decks bundled with keynotejs, and the deck new tables and charts are copied from.
 *
 * In Node they are read from the package's ``templates/`` folder. In a browser
 * they are fetched from the same place, relative to this module; a bundler
 * that moves modules around can serve them from elsewhere with
 * {@link setTemplateLoader}, or pass a theme deck's bytes to
 * ``Presentation.create({ template })``.
 */

import { Package } from "./package.js";

/** Themes bundled with keynotejs, each at 16:9 and 4:3. */
const THEMES = [
  "Basic Black",
  "Basic Color",
  "Basic White",
  "Briefing",
  "Classic White",
  "Color Gradient",
  "Minimalist Dark",
  "Minimalist Light",
];

/** Slide sizes for new presentations: ``"16:9"`` is 1920 x 1080 (Wide), ``"4:3"`` is 1024 x 768 (Standard). */
export type Aspect = "16:9" | "4:3";
export const ASPECTS: Aspect[] = ["16:9", "4:3"];

/** The bundled deck new tables and charts are copied from. */
export const PARTS_FILE = "parts/basic-white-parts.key";

/** Reads a bundled file, named relative to ``templates/``, e.g. ``"basic-white-16x9.key"``. */
export type TemplateLoader = (file: string) => Promise<Uint8Array>;

/** Names of the themes bundled with keynotejs, for ``Presentation.create``. */
export function themes(): string[] {
  return [...THEMES];
}

/** ``"<theme>-<aspect>.key"``, e.g. ``"basic-white-16x9.key"``, if the theme is bundled. */
export function templateFile(theme: string, aspect: Aspect): string {
  const wanted = theme.trim().toLowerCase();
  if (!THEMES.some((t) => t.toLowerCase() === wanted)) {
    const available = THEMES.flatMap((t) => ASPECTS.map((a) => `${t} (${a})`)).join(", ");
    throw new Error(`no bundled theme "${theme}" at ${aspect}; available: ${available}`);
  }
  return wanted.replaceAll(" ", "-") + "-" + aspect.replace(":", "x") + ".key";
}

async function defaultLoader(file: string): Promise<Uint8Array> {
  const url = new URL(`../templates/${file}`, import.meta.url);
  if (url.protocol === "file:") {
    // A variable keeps bundlers from trying to include Node's fs in browser builds.
    const fs = "node:fs/promises";
    const { readFile } = await import(/* @vite-ignore */ fs);
    return new Uint8Array(await readFile(url));
  }
  const response = await fetch(url);
  if (!response.ok) throw new Error(`couldn't fetch the bundled file ${url}: ${response.status} ${response.statusText}`);
  return new Uint8Array(await response.arrayBuffer());
}

let loader: TemplateLoader = defaultLoader;
let parts: Promise<Package> | null = null;
let partsReady: Package | null = null;

/**
 * Read bundled files some other way, e.g. from URLs your bundler gives them:
 *
 *     setTemplateLoader(async (file) => new Uint8Array(await (await fetch(`/keynote/${file}`)).arrayBuffer()));
 *
 * Pass ``null`` to go back to the default.
 */
export function setTemplateLoader(fn: TemplateLoader | null): void {
  loader = fn ?? defaultLoader;
  parts = null;
  partsReady = null;
}

export function loadTemplate(file: string): Promise<Uint8Array> {
  return loader(file);
}

/** Load the deck new tables and charts are copied from. ``Presentation.create`` and ``open`` do this for you. */
export function preload(): Promise<Package> {
  if (parts === null) {
    const loading = loader(PARTS_FILE).then((bytes) => (partsReady = Package.fromBytes(bytes)));
    loading.catch(() => {
      if (parts === loading) parts = null;
    });
    parts = loading;
  }
  return parts;
}

/** @internal The parts deck, which must have been loaded with {@link preload}. Never saved. */
export function partsPackage(): Package {
  if (partsReady === null) {
    throw new Error("tables and charts are copied from a bundled deck that isn't loaded yet: await preload() first");
  }
  return partsReady;
}
