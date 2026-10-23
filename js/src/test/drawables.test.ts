import { test } from "node:test";
import assert from "node:assert/strict";

import { Presentation, SHAPE_KINDS, Slide, fromMarkdown, parseColor, parseMarkdown } from "../index.js";
import type { Message } from "../protobuf.js";
import { componentIdOf } from "../drawables.js";
import { uuidValue } from "../package.js";
import { packDecimal128, tableUid, unpackDecimal128 } from "../tables.js";
import { assertNoDanglingReferences, fixture, reopen } from "./helpers.js";

const FIXTURE = "shapes-tables-charts.key";

// --- reading what Keynote wrote ---------------------------------------------------

test("reads Keynote's shapes", async () => {
  const deck = await fixture(FIXTURE);
  const [shape, box] = deck.slide(0).shapes;
  assert.equal(shape.kind, "rectangle");
  assert.deepEqual(shape.position, [200, 200]);
  assert.deepEqual(shape.size, [600, 400]);
  assert.equal(shape.text, "Hello shape");
  assert.equal(shape.fill, "#000000");
  assert.equal(box.kind, "text box");
  assert.equal(box.text, "Free text");
});

test("reads Keynote's table", async () => {
  const deck = await fixture(FIXTURE);
  const [table] = deck.slide(1).tables;
  assert.deepEqual([table.rowCount, table.columnCount, table.headerRows], [4, 3, 1]);
  assert.deepEqual(table.rows, [["Name", "Score", "Note"], ["Ada", 42, "first"], ["Bob", 3.5, "second"], ["Cy", -7, null]]);
  assert.equal(table.cell(2, 1), 3.5);
});

test("reads Keynote's charts", async () => {
  const deck = await fixture(FIXTURE);
  assert.deepEqual(deck.slides.slice(2).map((s) => s.charts[0].chartType), ["column", "line", "pie"]);
  const chart = deck.slide(2).charts[0];
  assert.deepEqual(chart.rowNames, ["2024", "2025"]);
  assert.deepEqual(chart.columnNames, ["Q1", "Q2", "Q3"]);
  assert.deepEqual(chart.data, [[1, 2, 3], [4, 5, 6]]);
  assert.equal(chart.seriesBy, "row");
  assert.deepEqual(chart.series, ["2024", "2025"]);
});

test("slides list drawables by kind", async () => {
  const deck = await fixture(FIXTURE);
  assert.deepEqual(deck.slide(0).drawables.map((d) => d.kind), ["rectangle", "text box"]);
  assert.ok(deck.slide(1).tables.length && !deck.slide(1).charts.length && !deck.slide(1).shapes.length);
});

// --- shapes -----------------------------------------------------------------------

test("add every shape kind", async () => {
  const deck = await Presentation.create();
  const slide = deck.addSlide("Blank");
  SHAPE_KINDS.forEach((kind, i) => slide.addShape(kind, { x: 10 + i, y: 20, width: 200, height: 100, text: kind, style: i % 6 }));
  slide.addTextBox("Free text", { x: 10, y: 900, width: 500, height: 60 });
  const out = await reopen(deck);
  const shapes = out.slide(0).shapes;
  assert.deepEqual(shapes.map((s) => s.kind), [...SHAPE_KINDS, "text box"]);
  assert.deepEqual(shapes.map((s) => s.text), [...SHAPE_KINDS, "Free text"]);
  assert.deepEqual(shapes[3].position, [13, 20]);
  assert.deepEqual(shapes[3].size, [200, 100]);
  assertNoDanglingReferences(out);
});

test("shape fill and resize", async () => {
  const deck = await Presentation.create();
  const shape = deck.addSlide("Blank").addShape("oval", { fill: "#3366ff" });
  assert.equal(shape.fill, "#3366ff");
  shape.size = [300, 150];
  shape.position = [5, 6];
  shape.fill = "orange";
  const [again] = (await reopen(deck)).slide(0).shapes;
  assert.equal(again.fill, "#ff9400");
  assert.deepEqual(again.size, [300, 150]);
  assert.deepEqual(again.position, [5, 6]);
  assert.equal(again.kind, "oval");
});

test("fill a shape Keynote made", async () => {
  const deck = await fixture(FIXTURE);
  deck.slide(0).shapes[0].fill = [1, 0, 0];
  assert.equal((await reopen(deck)).slide(0).shapes[0].fill, "#ff0000");
});

test("bad shape arguments", async () => {
  const slide = (await Presentation.create()).addSlide("Blank");
  assert.throws(() => slide.addShape("blob"));
  assert.throws(() => slide.addShape("rectangle", { width: 0 }));
  assert.throws(() => slide.addShape("rectangle", { style: 6 }));
});

test("parseColor", () => {
  assert.deepEqual(parseColor("#fff"), [1, 1, 1, 1]);
  assert.ok(Math.abs(parseColor("#00000080")[3] - 0.5) <= 0.01);
  assert.deepEqual(parseColor([0.5, 0.5, 0.5]), [0.5, 0.5, 0.5, 1]);
  assert.throws(() => parseColor("nope"));
});

test("build on a shape", async () => {
  const deck = await Presentation.create();
  const slide = deck.addSlide("Blank");
  slide.addBuild(slide.addShape("star"));
  const out = await reopen(deck);
  assert.equal(out.slide(0).builds[0].target, out.slide(0).shapes[0].identifier);
});

// --- charts -----------------------------------------------------------------------

test("add charts", async () => {
  const deck = await Presentation.create();
  const slide = deck.addSlide("Blank");
  slide.addChart("line", [[1, 2], [3, null]], ["A", "B"], ["x", "y"], { x: 10, y: 20, width: 500, height: 400, style: 3 });
  slide.addChart("pie", [[3, 5, 2]], ["Share"], ["a", "b", "c"], { width: 600, height: 400 });
  const out = await reopen(deck);
  const [line, pie] = out.slide(0).charts;
  assert.equal(line.chartType, "line");
  assert.deepEqual(line.data, [[1, 2], [3, null]]);
  assert.ok(line.showLegend);
  // The plot shrinks to leave room for the legend above it, inside the box.
  const [[px, py], [pw, ph]] = [line.position, line.size];
  const legend = (line as unknown as { chart: Message }).chart.legend_frame;
  const top = py + ph / 2 + legend.origin.y;
  assert.ok(px > 10 && px + pw === 510 && py + ph < 420); // room for axis labels too
  assert.ok(top >= 20 && top < py);
  assert.equal(pie.chartType, "pie");
  assert.equal(pie.seriesBy, "column"); // so the first row's values are the slices
  assert.ok(pie.size[0] === pie.size[1] && pie.size[0] < 400); // square, below its legend
  assertNoDanglingReferences(out);
});

test("set a chart's data and type", async () => {
  const deck = await fixture(FIXTURE);
  const chart = deck.slide(2).charts[0];
  chart.setData([[9, 8]], ["Only"], ["P", "Q"]);
  chart.chartType = "bar";
  const again = (await reopen(deck)).slide(2).charts[0];
  assert.deepEqual([again.chartType, again.rowNames, again.data], ["bar", ["Only"], [[9, 8]]]);
});

test("chart data must match its names", async () => {
  const slide = (await Presentation.create()).addSlide("Blank");
  assert.throws(() => slide.addChart("column", [[1, 2]], ["A"], ["x"]));
  assert.throws(() => slide.addChart("radial" as "column", [[1]], ["A"], ["x"]));
});

// --- tables -----------------------------------------------------------------------

type Tiled = { tiles(): [number, Message][] };

test("add a table", async () => {
  const deck = await Presentation.create();
  const slide = deck.addSlide("Title Only", { title: "Scores" });
  const rows = [["Name", "Score", "Note"], ["Ada", 42, "first"], ["Bob", 3.5, null], ["Cy", -7, true]];
  slide.addTable(rows, { headerColumns: 1, style: 2 });
  const out = await reopen(deck);
  const [table] = out.slide(0).tables;
  assert.deepEqual(table.rows, rows);
  assert.deepEqual([table.headerRows, table.headerColumns], [1, 1]);
  assert.deepEqual(table.size, [900, 256]);
  assert.equal(table.name, "Table 1");
  assertNoDanglingReferences(out);
});

test("cells are written byte for byte as Keynote writes them", async () => {
  const keynote = (await fixture(FIXTURE)).slide(1).tables[0];
  const ours = (await Presentation.create()).addSlide("Blank").addTable(keynote.rows);
  const a = (keynote as unknown as Tiled).tiles();
  const b = (ours as unknown as Tiled).tiles();
  assert.equal(a.length, b.length);
  a.forEach(([, x], i) => {
    const y = b[i][1];
    const field = (tile: Message, name: string) => (tile.rowInfos as Message[]).map((r) => r[name]);
    assert.deepEqual(field(x, "cell_storage_buffer"), field(y, "cell_storage_buffer"));
    assert.deepEqual(field(x, "cell_offsets"), field(y, "cell_offsets"));
  });
});

test("edit Keynote's table", async () => {
  const deck = await fixture(FIXTURE);
  const table = deck.slide(1).tables[0];
  table.setCell(3, 2, "third");
  table.setCell(1, 1, 43);
  const out = await reopen(deck);
  assert.deepEqual(out.slide(1).tables[0].rows.slice(1), [["Ada", 43, "first"], ["Bob", 3.5, "second"], ["Cy", -7, "third"]]);
});

test("resize a table", async () => {
  const deck = await fixture(FIXTURE);
  deck.slide(1).tables[0].setRows([["a", "b", "c", "d"], [1, 2, 3, 4], ...[0, 1, 2, 3, 4].map((i) => [i])]);
  const table = (await reopen(deck)).slide(1).tables[0];
  assert.deepEqual([table.rowCount, table.columnCount], [7, 4]);
  assert.deepEqual(table.rows[2], [0, null, null, null]);
  assert.equal(table.rowHeights.length, 7);
});

test("two tables get their own formula owners", async () => {
  const deck = await Presentation.create();
  const slide = deck.addSlide("Blank");
  const a = slide.addTable([["a"], [1]]);
  const b = slide.addTable([["b"], [2]]);
  assert.notEqual(a.model.table_id, b.model.table_id);
  const p = deck.package;
  const engine = p.get(p.componentForFile("Index/CalculationEngine.iwa").identifier);
  const entries = engine.dependency_tracker.owner_id_map.map_entry as Message[];
  const internal = entries.map((e) => e.internal_owner_id);
  assert.equal(new Set(internal).size, internal.length);
  const owners = entries.map((e) => String(e.owner_id.uuid_w0));
  assert.equal(new Set(owners).size, owners.length);
  assert.deepEqual((await reopen(deck)).slide(0).tables.map((t) => t.name), ["Table 1", "Table 2"]);
});

test("decimal128 round trip", () => {
  for (const value of [0, 1, -7, 42, 3.5, 0.1, 1e6, 123456.789, -0.0025]) {
    assert.ok(Math.abs(unpackDecimal128(packDecimal128(value)) - value) <= 1e-9 * Math.max(1, Math.abs(value)), String(value));
  }
});

// --- removing and copying -------------------------------------------------------------

test("deleting drawables leaves nothing behind", async () => {
  const deck = await Presentation.create();
  const slide = deck.addSlide("Blank");
  const before = [...deck.package.objects()].length;
  slide.addTable([["a", "b"], [1, 2]]);
  slide.addChart("column", [[1, 2]], ["x"], ["a", "b"]);
  slide.addShape("oval", { text: "hi" });
  for (const d of slide.drawables) slide.deleteDrawable(d);
  assert.deepEqual(slide.drawables, []);
  // Only the (now empty) object container Keynote keeps chart settings in is left.
  assert.equal([...deck.package.objects()].length, before + 1);
  const out = await reopen(deck);
  assert.deepEqual(out.slide(0).drawables, []);
  assertNoDanglingReferences(out);
});

test("duplicating a slide copies its tables and charts", async () => {
  const deck = await fixture(FIXTURE);
  deck.duplicateSlide(1).tables[0].setCell(1, 0, "Changed");
  deck.duplicateSlide(3).charts[0].setData([[1]], ["r"], ["c"]);
  const out = await reopen(deck);
  assert.equal(out.slide(1).tables[0].cell(1, 0), "Ada");
  assert.equal(out.slide(2).tables[0].cell(1, 0), "Changed");
  assert.notEqual(out.slide(1).tables[0].identifier, out.slide(2).tables[0].identifier);
  assert.deepEqual(out.slide(3).charts[0].data, [[1, 2, 3], [4, 5, 6]]);
  assert.deepEqual(out.slide(4).charts[0].data, [[1]]);
  assertNoDanglingReferences(out);
});

test("delete a slide with a table", async () => {
  const deck = await fixture(FIXTURE);
  deck.deleteSlide(1);
  const out = await reopen(deck);
  assert.ok(out.slides.every((s) => !s.tables.length));
  assert.deepEqual(out.package.filenames.filter((n) => n.startsWith("Index/Tables/")), []);
  assertNoDanglingReferences(out);
});

// --- Markdown ---------------------------------------------------------------------------

const MARKDOWN = `# Scores

| Name | Score | Note |
| --- | --- | --- |
| Ada | 42 | first |
| Bob | 3.5 | a \\| pipe |
| Cy | -7 |  |
`;

test("Markdown table round trip", async () => {
  const deck = await fromMarkdown(MARKDOWN);
  const [table] = deck.slide(0).tables;
  assert.equal(table.headerRows, 1);
  assert.deepEqual(table.rows, [["Name", "Score", "Note"], ["Ada", 42, "first"], ["Bob", 3.5, "a | pipe"], ["Cy", -7, null]]);
  assert.equal(deck.slide(0).layout, "Title Only");
  const md = (await reopen(deck)).toMarkdown();
  assert.ok(md.endsWith(MARKDOWN.split("\n").slice(2).join("\n")), md);
  assert.deepEqual(parseMarkdown(md)[0].tables, parseMarkdown(MARKDOWN)[0].tables);
});

test("Markdown table without a header", async () => {
  const [spec] = parseMarkdown("|  |  |\n| --- | --- |\n| a | TRUE |\n");
  assert.deepEqual(spec.tables[0].rows, [["a", true]]);
  assert.equal(spec.tables[0].headerRows, 0);
  const deck = await fromMarkdown("|  |  |\n| --- | --- |\n| a | TRUE |\n");
  assert.equal(deck.slide(0).layout, "Blank");
});

test("Keynote's table exports to Markdown", async () => {
  const deck = await fixture(FIXTURE);
  assert.ok(deck.toMarkdown().includes("| Name | Score | Note |\n| --- | --- | --- |\n| Ada | 42 | first |"));
});

function uuidString(value: bigint): string {
  const hex = Array.from({ length: 16 }, (_, i) => Number((value >> BigInt(8 * i)) & 0xffn).toString(16).padStart(2, "0")).join("");
  return [hex.slice(0, 8), hex.slice(8, 12), hex.slice(12, 16), hex.slice(16, 20), hex.slice(20)].join("-").toUpperCase();
}

test("a new table's id is its calculation engine UUID", async () => {
  // Keynote drops a table whose table_id isn't the UUID of its base formula owner.
  const keynote = await fixture(FIXTURE);
  const fresh = await Presentation.create();
  for (const [deck, table] of [
    [keynote, keynote.slide(1).tables[0]],
    [fresh, fresh.addSlide("Blank").addTable([["a"], [1]])],
  ] as const) {
    assert.equal(table.model.table_id, uuidString(uuidValue(tableUid(deck.package, table))));
  }
});

function slideRefersTo(slide: Slide, identifier: number): boolean {
  const p = slide.pkg;
  const component = p.component(componentIdOf(p, slide.slideId));
  return (component.external_references as Message[]).some((e) => e.object_identifier === identifier);
}

test("slides refer to their tables", async () => {
  // Keynote only loads a table (kept in the calculation engine's file) that its slide's component refers to.
  const deck = await fixture(FIXTURE);
  const added = deck.addSlide("Blank").addTable([["a", "b"], [1, 2]]);
  deck.duplicateSlide(1);
  const out = await reopen(deck);
  for (const slide of out) for (const table of slide.tables) assert.ok(slideRefersTo(slide, table.identifier));
  assert.notEqual(out.slide(2).tables[0].identifier, out.slide(1).tables[0].identifier);
  assert.ok(!slideRefersTo(out.slide(2), out.slide(1).tables[0].identifier));
  assert.ok(out.slide(out.length - 1).tables.some((t) => t.identifier === added.identifier));
});

test("deleting a placeholder table forgets it", async () => {
  const deck = await fixture(FIXTURE);
  const slide = deck.slide(1);
  const table = slide.tables[0];
  const geometry = (s: Slide) => ((s.slide.infos_using_object_placeholder_geometry ?? []) as Message[]).map((r) => r.identifier);
  assert.ok(geometry(slide).includes(table.identifier));
  slide.deleteDrawable(table);
  const out = await reopen(deck);
  assert.ok(!geometry(out.slide(1)).includes(table.identifier));
  assert.ok(!slideRefersTo(out.slide(1), table.identifier));
});

test("a copied table's UIDs are sorted", async () => {
  const deck = await fixture(FIXTURE);
  const copy = deck.duplicateSlide(1);
  const uids = copy.pkg.deref(copy.tables[0].model.base_column_row_uids);
  for (const kind of ["column", "row"]) {
    const keys = (uids[`sorted_${kind}_uids`] as Message[]).map((u) => (BigInt(u.upper) << 64n) | BigInt(u.lower));
    assert.deepEqual(keys, [...keys].sort((x, y) => (x < y ? -1 : x > y ? 1 : 0)));
    const indexForUid: number[] = uids[`${kind}_index_for_uid`];
    const uidForIndex: number[] = uids[`${kind}_uid_for_index`];
    assert.ok(indexForUid.every((index, pos) => uidForIndex[index] === pos));
  }
});
