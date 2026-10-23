// The template decks and licence live with the Python package; npm needs its own copies.
import { copyFileSync, cpSync, mkdirSync } from "node:fs";

const from = new URL("../../src/pykeynote/templates/", import.meta.url);
const to = new URL("../templates/", import.meta.url);
mkdirSync(to, { recursive: true });
cpSync(from, to, { recursive: true, filter: (src) => !src.endsWith(".py") });
copyFileSync(new URL("../../LICENSE", import.meta.url), new URL("../LICENSE", import.meta.url));
