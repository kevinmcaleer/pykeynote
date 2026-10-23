import { readdirSync, writeFileSync } from "node:fs";
import { Presentation } from "./dist/index.js";
for (const f of readdirSync("../tests/fixtures")) {
  const d = await Presentation.open("../tests/fixtures/"+f);
  writeFileSync(`/tmp/claude-0/cmp/${f}.js.md`, d.toMarkdown());
  writeFileSync(`/tmp/claude-0/cmp/${f}.js.json`, JSON.stringify({theme:d.theme,size:d.size,layouts:d.layouts,slides:d.slides.map(s=>s.toJSON())},null,1));
}
