/**
 * Tables: read and change cells, and add new tables.
 *
 * A table is a ``TST.TableInfoArchive`` (its frame on the slide) pointing at a
 * ``TST.TableModelArchive``, both kept in ``Index/CalculationEngine.iwa``.
 * The model's data store holds the cells in ``TST.Tile`` objects, one row of
 * up to 256 cells per ``TST.TileRowInfo``, each cell packed into a small
 * binary record. Text lives in a string list (``TST.TableDataList``) that
 * cells refer to by key, and each row and column has a header entry with its
 * height or width. Tiles, lists and headers are components of their own.
 *
 * Each table is also several "formula owners" in the calculation engine,
 * which knows them by UUID and by a small internal number.
 *
 * The cell record layout (storage version 5) follows numbers-parser's notes:
 * a 12-byte header (version, cell type, 2 unused bytes, 4 bytes, then 32 bits
 * of flags), then one field per flag in bit order. Flag 0x1 is a 16-byte
 * decimal, 0x2 and 0x4 are 8-byte doubles, every other flag is 4 bytes.
 *
 * New tables are copied from a table that Keynote made, in the bundled parts
 * deck, then resized and filled.
 */

import { CALC_ENGINE_FILE, Importer, ownedObjects, themePresets } from "./clone.js";
import type { Slide } from "./document.js";
import { Drawable, placeOnSlide, type DrawableJSON } from "./drawables.js";
import { METADATA_ID, headerRefs, int64, newUuidParts, uuidValue, type Package } from "./package.js";
import { clear, clone, create, fieldsOf, has, sub, typeOf, walk, type Message } from "./protobuf.js";
import { Text } from "./text.js";

/** What a cell can hold. Dates are read but not written. */
export type CellValue = null | string | number | boolean | Date;

const TILE_SIZE = 256; // rows per tile
const OFFSETS = 255; // cell offsets per tile row, as Keynote writes them
const EMPTY = 0, NUMBER = 2, TEXT = 3, DATE = 5, BOOL = 6, DURATION = 7, RICH = 9;

const DECIMAL = 0x1, DOUBLE = 0x2, SECONDS = 0x4, STRING = 0x8, RICH_ID = 0x10;
const SUGGEST = 0x1000, NUM_FORMAT = 0x2000, TEXT_FORMAT = 0x20000;
const FORMAT_FLAGS = [0x2000, 0x4000, 0x8000, 0x10000, 0x20000, 0x40000];
const VALUE_FLAGS = DECIMAL | DOUBLE | SECONDS | STRING | RICH_ID;
const EPOCH = Date.UTC(2001, 0, 1);

// Keynote 14.5 marks a text cell with suggest 5 and a number with suggest 1.
const SUGGEST_TEXT = 5, SUGGEST_NUMBER = 1;
// Format types (TSK.FormatStructArchive.format_type) for plain text and numbers.
const FORMAT_TEXT = 260, FORMAT_NUMBER = 256;

function fieldSize(flag: number): number {
  return flag === DECIMAL ? 16 : flag === DOUBLE || flag === SECONDS ? 8 : 4;
}

// --- decimals -----------------------------------------------------------------

export function unpackDecimal128(b: Uint8Array): number {
  const exponent = (((b[15] & 0x7f) << 7) | (b[14] >> 1)) - 0x1820;
  let mantissa = BigInt(b[14] & 1);
  for (let i = 13; i >= 0; i--) mantissa = mantissa * 256n + BigInt(b[i]);
  const value = Number(`${mantissa}e${exponent}`);
  return b[15] & 0x80 ? -value : value;
}

export function packDecimal128(value: number): Uint8Array {
  let text = String(value);
  const sign = text.startsWith("-") ? 1 : 0;
  text = text.replace(/^-/, "");
  let [mantissaText, expText] = text.split("e");
  let exponent = expText === undefined ? 0 : parseInt(expText, 10);
  let mantissa: bigint;
  if (mantissaText.includes(".")) {
    const [whole, rawFrac] = mantissaText.split(".");
    const frac = rawFrac.replace(/0+$/, "");
    mantissa = whole + frac ? BigInt(whole + frac) : 0n;
    exponent -= frac.length;
  } else {
    mantissa = BigInt(mantissaText);
  }
  const biased = exponent + 0x1820;
  const out = new Uint8Array(16);
  for (let i = 0; i < 14; i++) {
    out[i] = Number(mantissa & 0xffn);
    mantissa >>= 8n;
  }
  out[14] = ((biased & 0x7f) << 1) | Number(mantissa & 1n);
  out[15] = (sign << 7) | ((biased >> 7) & 0x7f);
  return out;
}

// --- cell records ---------------------------------------------------------------

function doubleBytes(value: number): Uint8Array {
  const out = new Uint8Array(8);
  new DataView(out.buffer).setFloat64(0, value, true);
  return out;
}

function readDouble(b: Uint8Array): number {
  return new DataView(b.buffer, b.byteOffset, 8).getFloat64(0, true);
}

/** One cell record: its type and its fields, keyed by flag. */
class Cell {
  constructor(
    public type = EMPTY,
    readonly fields = new Map<number, Uint8Array>(),
    readonly extra: Uint8Array = new Uint8Array(6), // bytes 2-7 of the header, kept as they were
  ) {}

  static unpack(buf: Uint8Array): Cell {
    const view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
    const flags = view.getUint32(8, true);
    let offset = 12;
    const fields = new Map<number, Uint8Array>();
    for (let bit = 0; bit < 32; bit++) {
      const flag = (1 << bit) >>> 0;
      if (flags & flag) {
        const size = fieldSize(flag);
        fields.set(flag, buf.slice(offset, offset + size));
        offset += size;
      }
    }
    return new Cell(buf[1], fields, buf.slice(2, 8));
  }

  pack(): Uint8Array {
    let flags = 0;
    const order = [...this.fields.keys()].sort((a, b) => a - b);
    const length = order.reduce((n, f) => n + this.fields.get(f)!.length, 12);
    const out = new Uint8Array(length);
    out[0] = 5;
    out[1] = this.type;
    out.set(this.extra, 2);
    let offset = 12;
    for (const flag of order) {
      flags = (flags | flag) >>> 0;
      out.set(this.fields.get(flag)!, offset);
      offset += this.fields.get(flag)!.length;
    }
    new DataView(out.buffer).setUint32(8, flags, true);
    return out;
  }

  intField(flag: number): number | null {
    const raw = this.fields.get(flag);
    return raw === undefined ? null : new DataView(raw.buffer, raw.byteOffset, 4).getInt32(0, true);
  }

  setInt(flag: number, value: number): void {
    const out = new Uint8Array(4);
    new DataView(out.buffer).setInt32(0, value, true);
    this.fields.set(flag, out);
  }
}

/** The cells in one tile row, by column. */
function tileCells(row: Message): Map<number, Cell> {
  const buf: Uint8Array = row.cell_storage_buffer;
  const raw: Uint8Array = row.cell_offsets;
  const view = new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
  const out = new Map<number, Cell>();
  for (let column = 0; column < raw.length >> 1; column++) {
    let offset = view.getUint16(column * 2, true);
    if (offset === 0xffff) continue;
    if (row.has_wide_offsets) offset *= 4;
    out.set(column, Cell.unpack(buf.subarray(offset)));
  }
  return out;
}

function packOffsets(offsets: number[]): Uint8Array {
  const out = new Uint8Array(offsets.length * 2);
  const view = new DataView(out.buffer);
  offsets.forEach((o, i) => view.setUint16(i * 2, o, true));
  return out;
}

function writeTileRow(row: Message, cells: Map<number, Cell>): void {
  const records: Uint8Array[] = [];
  const offsets = new Array<number>(OFFSETS).fill(0xffff);
  const preOffsets = new Array<number>(OFFSETS).fill(0xffff);
  let length = 0;
  let columns = 0;
  for (const column of [...cells.keys()].sort((a, b) => a - b)) {
    const record = cells.get(column)!.pack();
    offsets[column] = length;
    records.push(record);
    length += record.length;
    // Older readers see an empty version 4 cell in the same place.
    preOffsets[column] = columns * 12;
    columns++;
  }
  if (length > 0xfffe) throw new Error("too much data in one table row");
  const buf = new Uint8Array(length);
  let at = 0;
  for (const r of records) {
    buf.set(r, at);
    at += r.length;
  }
  const preBuf = new Uint8Array(columns * 12);
  for (let i = 0; i < columns; i++) preBuf[i * 12] = 4;
  row.cell_storage_buffer = buf;
  row.cell_offsets = packOffsets(offsets);
  row.cell_storage_buffer_pre_bnc = preBuf;
  row.cell_offsets_pre_bnc = packOffsets(preOffsets);
  row.cell_count = cells.size;
  row.storage_version = 5;
  clear(row, "has_wide_offsets");
}

// --- tables ---------------------------------------------------------------------

function keyEntries(dataList: Message): Map<number, Message> {
  return new Map((dataList.entries as Message[]).map((e) => [e.key, e]));
}

const cellKey = (row: number, column: number) => `${row},${column}`;

/** A table on a slide. Rows and columns count from 0, header rows included. */
export class Table extends Drawable {
  override get kind(): string {
    return "table";
  }

  /** @internal */
  get model(): Message {
    return this.pkg.deref(this.archive.tableModel);
  }

  private get modelId(): number {
    return this.archive.tableModel.identifier;
  }

  private get store(): Message {
    return this.model.base_data_store;
  }

  get name(): string {
    return this.model.table_name;
  }

  set name(value: string) {
    this.model.table_name = value;
    this.pkg.markChanged(this.modelId);
    this.slide.touched();
  }

  get rowCount(): number {
    return this.model.number_of_rows;
  }

  get columnCount(): number {
    return this.model.number_of_columns;
  }

  get headerRows(): number {
    return this.model.number_of_header_rows;
  }

  get headerColumns(): number {
    return this.model.number_of_header_columns;
  }

  get footerRows(): number {
    return this.model.number_of_footer_rows;
  }

  private tiles(): [number, Message][] {
    return (this.store.tiles.tiles as Message[]).map((t) => [t.tileid, this.pkg.deref(t.tile)]);
  }

  private cells(): Map<string, Cell> {
    const out = new Map<string, Cell>();
    for (const [tileId, tile] of this.tiles()) {
      for (const row of tile.rowInfos as Message[]) {
        for (const [column, cell] of tileCells(row)) out.set(cellKey(tileId * TILE_SIZE + row.tile_row_index, column), cell);
      }
    }
    return out;
  }

  private value(cell: Cell): CellValue {
    const p = this.pkg;
    if (cell.type === TEXT && cell.fields.has(STRING)) {
      const entry = keyEntries(p.deref(this.store.stringTable)).get(cell.intField(STRING)!);
      return entry === undefined ? null : entry.string;
    }
    if (cell.type === RICH && cell.fields.has(RICH_ID)) {
      const entry = keyEntries(p.deref(this.store.rich_text_table)).get(cell.intField(RICH_ID)!);
      if (entry !== undefined && has(entry, "rich_text_payload")) {
        const payload = p.deref(entry.rich_text_payload);
        return new Text(p, payload.storage.identifier).toString();
      }
      return null;
    }
    if (cell.type === NUMBER || cell.type === 10) {
      if (cell.fields.has(DECIMAL)) return unpackDecimal128(cell.fields.get(DECIMAL)!);
      if (cell.fields.has(DOUBLE)) return readDouble(cell.fields.get(DOUBLE)!);
      return null;
    }
    if (cell.type === BOOL && cell.fields.has(DOUBLE)) return Boolean(readDouble(cell.fields.get(DOUBLE)!));
    if (cell.type === DATE && cell.fields.has(SECONDS)) return new Date(EPOCH + readDouble(cell.fields.get(SECONDS)!) * 1000);
    if (cell.type === DURATION && cell.fields.has(DOUBLE)) return readDouble(cell.fields.get(DOUBLE)!);
    return null;
  }

  /** Every cell's value, row by row: text, a number, ``true``/``false``, a ``Date``, or ``null`` if empty. */
  get rows(): CellValue[][] {
    const grid: CellValue[][] = Array.from({ length: this.rowCount }, () => new Array<CellValue>(this.columnCount).fill(null));
    for (const [key, cell] of this.cells()) {
      const [r, c] = key.split(",").map(Number);
      if (r < this.rowCount && c < this.columnCount) grid[r][c] = this.value(cell);
    }
    return grid;
  }

  cell(row: number, column: number): CellValue {
    this.check(row, column);
    return this.rows[row][column];
  }

  private check(row: number, column: number): void {
    if (!(row >= 0 && row < this.rowCount && column >= 0 && column < this.columnCount)) {
      throw new RangeError(`cell (${row}, ${column}) is outside the ${this.rowCount} x ${this.columnCount} table`);
    }
  }

  setCell(row: number, column: number, value: CellValue): void {
    this.check(row, column);
    const grid = this.rows;
    grid[row][column] = value;
    this.write(grid, this.cells());
  }

  /** Replace every cell, resizing the table to fit. Row heights and column widths are kept where they exist. */
  setRows(rows: CellValue[][]): void {
    const grid = toGrid(rows);
    this.resize(grid.length, grid[0].length);
    this.write(grid, this.cells());
  }

  // --- writing ----------------------------------------------------------------

  private formatKey(formatType: number): number {
    const p = this.pkg;
    const table = p.deref(this.store.format_table);
    for (const e of table.entries as Message[]) if (sub(e, "format").format_type === formatType) return e.key;
    const key = table.nextListID || 1;
    table.nextListID = key + 1;
    const format = create("TSK.FormatStructArchive", { format_type: formatType });
    if (formatType === FORMAT_NUMBER) {
      format.decimal_places = 253;
      format.negative_style = 0;
      format.show_thousands_separator = false;
    }
    table.entries.push(create("TST.TableDataList.ListEntry", { key, refcount: 0, format }));
    p.markChanged(this.store.format_table.identifier);
    return key;
  }

  /** @internal Write every cell from ``grid``, keeping styles and formats of cells whose kind doesn't change. */
  write(grid: CellValue[][], keep: Map<string, Cell>): void {
    const p = this.pkg;
    const strings = p.deref(this.store.stringTable);
    const textKey = this.formatKey(FORMAT_TEXT);
    const numberKey = this.formatKey(FORMAT_NUMBER);
    const stringKeys = new Map<string, number>();
    strings.entries = [];
    let nextKey = 1;

    const rows = new Map<number, Map<number, Cell>>();
    grid.forEach((row, r) => {
      row.forEach((value, c) => {
        const old = keep.get(cellKey(r, c));
        const cell = old !== undefined ? new Cell(EMPTY, new Map(), old.extra) : new Cell();
        if (old !== undefined) {
          // Keep the cell's own style and anything else that isn't its value or format.
          for (const [flag, raw] of old.fields) {
            if (!(flag & VALUE_FLAGS) && !FORMAT_FLAGS.includes(flag) && flag !== SUGGEST) cell.fields.set(flag, raw);
          }
        }
        if (value === null || value === undefined || value === "") {
          if (!cell.fields.size) return;
          cell.type = EMPTY;
        } else if (typeof value === "boolean") {
          cell.type = BOOL;
          cell.fields.set(DOUBLE, doubleBytes(value ? 1.0 : 0.0));
        } else if (typeof value === "number") {
          if (!Number.isFinite(value)) throw new TypeError(`a cell can't hold ${value}`);
          cell.type = NUMBER;
          cell.fields.set(DECIMAL, packDecimal128(value));
          cell.setInt(SUGGEST, SUGGEST_NUMBER);
          cell.setInt(NUM_FORMAT, numberKey);
        } else if (typeof value === "string") {
          if (!stringKeys.has(value)) {
            stringKeys.set(value, nextKey);
            strings.entries.push(create("TST.TableDataList.ListEntry", { key: nextKey, refcount: 0, string: value }));
            nextKey++;
          }
          cell.type = TEXT;
          cell.setInt(STRING, stringKeys.get(value)!);
          cell.setInt(SUGGEST, SUGGEST_TEXT);
          cell.setInt(TEXT_FORMAT, textKey);
        } else {
          throw new TypeError(`a cell can hold text, a number, true/false or null, not ${Object.prototype.toString.call(value)}`);
        }
        if (!rows.has(r)) rows.set(r, new Map());
        rows.get(r)!.set(c, cell);
      });
    });
    strings.nextListID = nextKey;
    p.markChanged(this.store.stringTable.identifier);

    // Tiles: one per 256 rows.
    const tiles = this.tiles();
    const needed = Math.ceil(grid.length / TILE_SIZE);
    if (needed > tiles.length) throw new Error(`tables of more than ${tiles.length * TILE_SIZE} rows aren't supported`);
    for (const [tileId, tile] of tiles) {
      tile.rowInfos = [];
      const first = tileId * TILE_SIZE;
      let count = 0;
      for (let r = first; r < Math.min(first + TILE_SIZE, grid.length); r++) {
        const info = create("TST.TileRowInfo", { tile_row_index: r - first });
        writeTileRow(info, rows.get(r) ?? new Map());
        tile.rowInfos.push(info);
        count++;
      }
      tile.numrows = count;
      tile.maxColumn = tile.maxRow = tile.numCells = 0;
      tile.storage_version = 5;
      tile.last_saved_in_BNC = true;
    }
    for (const t of this.store.tiles.tiles as Message[]) p.markChanged(t.tile.identifier);

    // Reference counts and per-row/column cell counts.
    const counts = new Map<number, number>();
    const stringEntries = keyEntries(strings);
    for (const row of rows.values()) {
      for (const cell of row.values()) {
        for (const flag of FORMAT_FLAGS) {
          const key = cell.intField(flag);
          if (key !== null) counts.set(key, (counts.get(key) ?? 0) + 1);
        }
        const key = cell.intField(STRING);
        if (key !== null) stringEntries.get(key)!.refcount += 1;
      }
    }
    const formats = p.deref(this.store.format_table);
    for (const e of formats.entries as Message[]) e.refcount = counts.get(e.key) ?? 0;
    formats.entries = (formats.entries as Message[]).filter((e) => e.refcount > 0);
    p.markChanged(this.store.format_table.identifier);

    for (const header of this.rowHeaders()) header.numberOfCells = rows.get(header.index)?.size ?? 0;
    for (const header of this.columnHeaders()) {
      header.numberOfCells = [...rows.values()].filter((row) => row.has(header.index)).length;
    }
    this.headersChanged();
    this.slide.touched();
    p.markChanged(this.modelId);
  }

  // --- size -------------------------------------------------------------------

  private rowBucket(): Message {
    return this.pkg.deref(this.store.rowHeaders.buckets[0]);
  }

  private columnBucket(): Message {
    return this.pkg.deref(this.store.columnHeaders);
  }

  private rowHeaders(): Message[] {
    return [...this.rowBucket().headers];
  }

  private columnHeaders(): Message[] {
    return [...this.columnBucket().headers];
  }

  private headersChanged(): void {
    this.pkg.markChanged(this.store.rowHeaders.buckets[0].identifier);
    this.pkg.markChanged(this.store.columnHeaders.identifier);
  }

  get rowHeights(): number[] {
    const sizes = new Map(this.rowHeaders().map((h) => [h.index, h.size]));
    const fallback = this.model.default_row_height;
    return Array.from({ length: this.rowCount }, (_, i) => sizes.get(i) || fallback);
  }

  get columnWidths(): number[] {
    const sizes = new Map(this.columnHeaders().map((h) => [h.index, h.size]));
    const fallback = this.model.default_column_width;
    return Array.from({ length: this.columnCount }, (_, i) => sizes.get(i) || fallback);
  }

  setRowHeights(heights: number[]): void {
    this.setSizes(this.rowBucket(), this.rowCount, heights);
  }

  setColumnWidths(widths: number[]): void {
    this.setSizes(this.columnBucket(), this.columnCount, widths);
  }

  private setSizes(bucket: Message, count: number, sizes: number[]): void {
    if (sizes.length !== count) throw new Error(`need ${count} sizes, not ${sizes.length}`);
    const existing = new Map((bucket.headers as Message[]).map((h) => [h.index, h]));
    sizes.forEach((size, i) => {
      let h = existing.get(i);
      if (h === undefined) {
        h = create("TST.HeaderStorageBucket.Header", { index: i, hidingState: 0, numberOfCells: 0 });
        bucket.headers.push(h);
      }
      h.size = Number(size);
    });
    this.fitFrame();
    this.headersChanged();
  }

  private fitFrame(): void {
    const s = this.info.geometry.size;
    s.width = this.columnWidths.reduce((a, b) => a + b, 0);
    s.height = this.rowHeights.reduce((a, b) => a + b, 0);
    this.pkg.markChanged(this.identifier);
    this.slide.touched();
  }

  override resized(): void {
    // Spread the new frame over the rows and columns in proportion.
    const { width, height } = this.info.geometry.size;
    const widths = this.columnWidths;
    const heights = this.rowHeights;
    const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);
    this.setColumnWidths(widths.map((w) => (w * width) / sum(widths)));
    this.setRowHeights(heights.map((h) => (h * height) / sum(heights)));
  }

  /** @internal */
  resize(rows: number, columns: number): void {
    if (rows < 1 || columns < 1) throw new Error("a table needs at least one row and one column");
    if (columns > OFFSETS) throw new Error(`tables of more than ${OFFSETS} columns aren't supported`);
    const m = this.model;
    const heights = this.rowHeights;
    const widths = this.columnWidths;
    for (const [bucket, count, fallback] of [
      [this.rowBucket(), rows, heights[heights.length - 1]],
      [this.columnBucket(), columns, widths[widths.length - 1]],
    ] as [Message, number, number][]) {
      const existing = new Map((bucket.headers as Message[]).map((h) => [h.index, h]));
      bucket.headers = Array.from({ length: count }, (_, i) =>
        existing.has(i) ? existing.get(i)! : create("TST.HeaderStorageBucket.Header", { index: i, size: fallback, hidingState: 0, numberOfCells: 0 }),
      );
    }
    m.number_of_rows = rows;
    m.number_of_columns = columns;
    m.number_of_header_rows = Math.min(m.number_of_header_rows, rows);
    m.number_of_header_columns = Math.min(m.number_of_header_columns, columns);
    m.number_of_footer_rows = Math.min(m.number_of_footer_rows, rows - m.number_of_header_rows);
    setUids(this.pkg.deref(m.base_column_row_uids), rows, columns);
    this.pkg.markChanged(m.base_column_row_uids.identifier);
    this.pkg.markChanged(this.modelId);
    this.fitFrame();
    this.headersChanged();
  }

  /** Set how many header rows, header columns and footer rows the table has. */
  setHeaders(options: { rows?: number; columns?: number; footerRows?: number }): void {
    const m = this.model;
    const { rows, columns, footerRows } = options;
    if (rows !== undefined) {
      if (!(rows >= 0 && rows <= Math.min(5, this.rowCount))) throw new Error("header rows must be 0 to 5, and no more than the table has");
      m.number_of_header_rows = rows;
    }
    if (columns !== undefined) {
      if (!(columns >= 0 && columns <= Math.min(5, this.columnCount))) {
        throw new Error("header columns must be 0 to 5, and no more than the table has");
      }
      m.number_of_header_columns = columns;
    }
    if (footerRows !== undefined) {
      if (!(footerRows >= 0 && footerRows <= Math.min(5, this.rowCount - m.number_of_header_rows))) {
        throw new Error("footer rows must be 0 to 5, and fit below the header rows");
      }
      m.number_of_footer_rows = footerRows;
    }
    this.pkg.markChanged(this.modelId);
    this.slide.touched();
  }

  override toJSON(): DrawableJSON {
    const d = super.toJSON();
    return { ...d, name: this.name, headerRows: this.headerRows, headerColumns: this.headerColumns, rows: this.rows };
  }

  override beforeDelete(): void {
    unregisterHeaderNames(this.pkg, this);
  }

  override ownedElsewhere(owned: number[]): number[] {
    // The table's formula owners in the calculation engine, and what they own.
    const out: number[] = [];
    for (const i of tableOwners(this.pkg, owned)) out.push(...ownedObjects(this.pkg, i, new Set(owned)));
    return out;
  }
}

function toGrid(rows: CellValue[][]): CellValue[][] {
  const copy = [...rows].map((r) => [...r]);
  if (!copy.length || !copy.some((r) => r.length)) throw new Error("a table needs at least one row and one column");
  const width = Math.max(...copy.map((r) => r.length));
  return copy.map((r) => [...r, ...new Array<CellValue>(width - r.length).fill(null)]);
}

const uuidOrder = (a: [bigint, bigint], b: [bigint, bigint]) => (a[1] !== b[1] ? (a[1] < b[1] ? -1 : 1) : a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0);

/** Give every row and column a UUID, as ``TST.ColumnRowUIDMapArchive`` lists them. */
function setUids(uidMap: Message, rows: number, columns: number): void {
  for (const [kind, count] of [["column", columns], ["row", rows]] as [string, number][]) {
    const uids = Array.from({ length: count }, () => newUuidParts().map((v) => BigInt(v)) as [bigint, bigint]);
    const order = [...uids.keys()].sort((a, b) => uuidOrder(uids[a], uids[b]));
    uidMap[`sorted_${kind}_uids`] = order.map((i) => create("TSP.UUID", { lower: int64(uids[i][0]), upper: int64(uids[i][1]) }));
    uidMap[`${kind}_index_for_uid`] = order; // the index of each sorted UUID
    const position = new Map(order.map((index, pos) => [index, pos]));
    uidMap[`${kind}_uid_for_index`] = Array.from({ length: count }, (_, i) => position.get(i)); // where each index's UUID sits
  }
}

/** Re-sort the row and column UUIDs by (upper, lower), as Keynote keeps them, after they were renewed. */
function sortUids(uidMap: Message): void {
  for (const kind of ["column", "row"]) {
    const sorted: Message[] = uidMap[`sorted_${kind}_uids`];
    const indexForUid: number[] = uidMap[`${kind}_index_for_uid`];
    const pairs = sorted.map((u, i) => ({ key: [BigInt(u.lower), BigInt(u.upper)] as [bigint, bigint], u, index: indexForUid[i] }));
    pairs.sort((a, b) => uuidOrder(a.key, b.key));
    const position = new Array<number>(uidMap[`${kind}_uid_for_index`].length).fill(0);
    pairs.forEach((pair, pos) => (position[pair.index] = pos));
    uidMap[`sorted_${kind}_uids`] = pairs.map((pair) => pair.u);
    uidMap[`${kind}_index_for_uid`] = pairs.map((pair) => pair.index);
    uidMap[`${kind}_uid_for_index`] = position;
  }
}

// --- adding tables ----------------------------------------------------------------

const INTERNAL_ID_FIELDS = ["internal_formula_owner_id", "internal_owner_id", "internal_owner_id_for_edge"];
const TABLE_FORMULAS = 6; // formulas each new table brings, by the count Keynote 14.5 keeps

function uuidsIn(message: Message): Set<bigint> {
  const found = new Set<bigint>();
  walk(message, (m) => {
    const t = typeOf(m);
    if (t === "TSP.UUID" || t === "TSP.CFUUIDArchive") found.add(uuidValue(m));
  });
  return found;
}

function calcEngine(pkg: Package): [number, Message] {
  const identifier: number = pkg.componentForFile(CALC_ENGINE_FILE).identifier;
  return [identifier, pkg.get(identifier)];
}

/** The calculation engine's ``FormulaOwnerDependenciesArchive`` objects for a table. */
function tableOwners(donor: Package, closure: number[]): number[] {
  const uuids = new Set<bigint>();
  for (const i of closure) {
    try {
      for (const u of uuidsIn(donor.get(i))) uuids.add(u);
    } catch {
      // an archive keynotejs can't read holds no UUIDs we need
    }
  }
  const [, engine] = calcEngine(donor);
  const refs = engine.dependency_tracker.formula_owner_dependencies as Message[];
  const deps = refs.map((r) => donor.deref(r));
  const bases = new Set(deps.filter((d) => has(d, "base_owner_uid") && uuids.has(uuidValue(d.formula_owner_uid))).map((d) => uuidValue(d.base_owner_uid)));
  return refs.filter((_, i) => uuids.has(uuidValue(deps[i].formula_owner_uid)) || bases.has(uuidValue(deps[i].formula_owner_uid))).map((r) => r.identifier);
}

/** Give copied formula owners new internal numbers and list them in the calculation engine. */
function registerOwners(pkg: Package, ownerIds: number[]): void {
  const [engineId, engine] = calcEngine(pkg);
  const tracker = engine.dependency_tracker;
  const idMap = tracker.owner_id_map ?? (tracker.owner_id_map = create("TSCE.OwnerIDMapArchive"));
  const used: number[] = (idMap.map_entry as Message[]).map((e) => e.internal_owner_id);
  for (const r of tracker.formula_owner_dependencies as Message[]) {
    if (pkg.has(r.identifier)) used.push(pkg.get(r.identifier).internal_formula_owner_id);
  }
  let nextId = (used.length ? Math.max(...used) : 0) + 1;
  const internal = new Map<number, number>();
  for (const i of ownerIds) internal.set(pkg.get(i).internal_formula_owner_id, nextId++);

  const renumber = (message: Message) =>
    walk(message, (m) => {
      const fields = fieldsOf(typeOf(m));
      for (const name of INTERNAL_ID_FIELDS) {
        const f = fields.find((g) => g.name === name);
        if (f === undefined) continue;
        if (f.repeated) {
          if (has(m, name)) m[name] = (m[name] as number[]).map((v) => internal.get(v) ?? v);
        } else if (has(m, name) && internal.has(m[name])) {
          m[name] = internal.get(m[name]);
        }
      }
    });

  const seen = new Set<number>();
  const todo = [...ownerIds];
  while (todo.length) {
    const i = todo.pop()!;
    if (seen.has(i)) continue;
    seen.add(i);
    try {
      renumber(pkg.get(i));
    } catch {
      continue; // an archive keynotejs can't read
    }
    pkg.markChanged(i);
    todo.push(...headerRefs(pkg, i));
  }

  for (const i of ownerIds) {
    const deps = pkg.get(i);
    const value = uuidValue(deps.formula_owner_uid);
    const ownerId = create("TSP.CFUUIDArchive");
    for (let n = 0; n < 4; n++) ownerId[`uuid_w${n}`] = Number((value >> BigInt(32 * n)) & 0xffffffffn);
    idMap.map_entry.push(create("TSCE.OwnerIDMapArchive.OwnerIDMapArchiveEntry", { internal_owner_id: deps.internal_formula_owner_id, owner_id: ownerId }));
    tracker.formula_owner_dependencies.push(create("TSP.Reference", { identifier: i }));
    pkg.addObjectReference(engineId, i);
  }
  tracker.number_of_formulas = Number(tracker.number_of_formulas) + TABLE_FORMULAS;
  pkg.markChanged(engineId);
}

/** @internal Copy the table ``root`` from the importer's source package onto ``slide``. It isn't placed on the slide. */
export function copyTable(importer: Importer, root: number, srcSlideId: number, slide: Slide): Table {
  upgradeCalcEngine(importer.dst);
  const owners = tableOwners(importer.src, importer.closure(root, new Set([srcSlideId])));
  const idMap = importer.copyDrawable(root, srcSlideId, slide.slideId, owners);
  registerOwners(importer.dst, owners.map((i) => idMap.get(i)!));
  const table = new Table(slide, idMap.get(root)!);
  const uids = table.model.base_column_row_uids;
  sortUids(importer.dst.deref(uids));
  importer.dst.markChanged(uids.identifier);
  registerHeaderNames(importer.dst, table);
  return table;
}

// The calculation engine format Keynote 14.5 saves, with formula owners kept in
// their own archives rather than inline. Seed templates may predate it.
const ENGINE_FEATURE = "TSCEReduceCalcEngineMsgSize";
const ENGINE_VERSION = [3, 2, 10];

/** Switch an older calculation engine to the layout Keynote 14.5 writes, so it finds new tables. */
function upgradeCalcEngine(pkg: Package): void {
  const component = pkg.componentForFile(CALC_ENGINE_FILE);
  if ((component.feature_infos as Message[]).some((f) => f.identifier === ENGINE_FEATURE)) return;
  component.feature_infos.push(create("TSP.FeatureInfo", { identifier: ENGINE_FEATURE, read_version: [...ENGINE_VERSION], write_version: [...ENGINE_VERSION] }));
  component.document_read_version = [...ENGINE_VERSION];
  component.document_write_version = [...ENGINE_VERSION];
  const [engineId, engine] = calcEngine(pkg);
  const tracker = engine.dependency_tracker;
  const owners = new Set((tracker.formula_owner_dependencies as Message[]).map((r) => uuidValue(pkg.get(r.identifier).formula_owner_uid)));
  const inline = (tracker.formula_owner_info as Message[]).map((i) => uuidValue(i.formula_owner_id));
  if (inline.every((u) => owners.has(u))) clear(tracker, "formula_owner_info"); // each one is also kept as its own archive
  // The header name manager names the named-reference manager's owner.
  const names = pkg.deref(engine.header_name_manager);
  for (const r of tracker.formula_owner_dependencies as Message[]) {
    const deps = pkg.get(r.identifier);
    const nrm = sub(names, "nrm_owner_uid");
    if (deps.owner_kind === 7 && !(BigInt(nrm.lower) || BigInt(nrm.upper))) {
      names.nrm_owner_uid = clone(deps.formula_owner_uid);
      pkg.markChanged(engine.header_name_manager.identifier);
    }
  }
  pkg.markChanged(engineId);
  pkg.markChanged(METADATA_ID);
}

/** List a new table with the header name manager, as Keynote does for every table. */
function registerHeaderNames(pkg: Package, table: Table): void {
  const [, engine] = calcEngine(pkg);
  const names = pkg.deref(engine.header_name_manager);
  const tracker = engine.dependency_tracker;
  let documentOwner: number | undefined;
  for (const r of tracker.formula_owner_dependencies as Message[]) {
    if (uuidValue(pkg.get(r.identifier).formula_owner_uid) === uuidValue(names.owner_uid)) documentOwner = r.identifier;
  }
  if (documentOwner === undefined) return;
  const deps = pkg.get(documentOwner);
  const cellDeps = deps.cell_dependencies ?? (deps.cell_dependencies = create("TSCE.CellDependenciesExpandedArchive"));
  const used = new Set<number>((cellDeps.cell_record as Message[]).filter((rec) => rec.row === 1).map((rec) => rec.column));
  for (const e of names.per_tables as Message[]) used.add(e.per_table_precedent.column);
  const column = (used.size ? Math.max(...used) : -1) + 1;

  const m = table.model;
  const uidMap = pkg.deref(m.base_column_row_uids);
  const headerRowUids: Message[] = [];
  for (let row = 0; row < m.number_of_header_rows; row++) headerRowUids.push(clone(uidMap.sorted_row_uids[uidMap.row_uid_for_index[row]]));
  names.per_tables.push(
    create("TST.HeaderNameMgrArchive.PerTableArchive", {
      table_uid: clone(tableUid(pkg, table)),
      per_table_precedent: create("TSCE.CellCoordinateArchive", { column, row: 1 }),
      header_row_uids: headerRowUids,
    }),
  );
  pkg.markChanged(engine.header_name_manager.identifier);

  const record = () =>
    create("TSCE.CellRecordExpandedArchive", {
      column,
      row: 1,
      expanded_edges: create("TSCE.ExpandedEdgesArchive", { edge_without_owner_rows: [0], edge_without_owner_columns: [0] }),
    });
  cellDeps.cell_record.push(record());
  const tiles = sub(deps, "tiled_cell_dependencies").cell_record_tiles as Message[];
  if (tiles.length) {
    pkg.deref(tiles[0]).cell_records.push(record());
    pkg.markChanged(tiles[0].identifier);
  }
  pkg.markChanged(documentOwner);
}

function unregisterHeaderNames(pkg: Package, table: Table): void {
  let uid: bigint;
  try {
    uid = uuidValue(tableUid(pkg, table));
  } catch {
    return;
  }
  const [, engine] = calcEngine(pkg);
  const names = pkg.deref(engine.header_name_manager);
  const perTables = names.per_tables as Message[];
  const gone = new Set(perTables.filter((e) => uuidValue(e.table_uid) === uid).map((e) => e.per_table_precedent.column as number));
  if (!gone.size) return;
  names.per_tables = perTables.filter((e) => uuidValue(e.table_uid) !== uid);
  pkg.markChanged(engine.header_name_manager.identifier);
  const keep = (c: Message) => !(c.row === 1 && gone.has(c.column));
  for (const r of engine.dependency_tracker.formula_owner_dependencies as Message[]) {
    const deps = pkg.get(r.identifier);
    if (uuidValue(deps.formula_owner_uid) !== uuidValue(names.owner_uid)) continue;
    if (has(deps, "cell_dependencies")) deps.cell_dependencies.cell_record = (deps.cell_dependencies.cell_record as Message[]).filter(keep);
    for (const tileRef of sub(deps, "tiled_cell_dependencies").cell_record_tiles as Message[]) {
      const tile = pkg.deref(tileRef);
      tile.cell_records = (tile.cell_records as Message[]).filter(keep);
      pkg.markChanged(tileRef.identifier);
    }
    pkg.markChanged(r.identifier);
  }
}

/** The UUID the calculation engine knows the table by: the owner every other owner of it is based on. */
/** @internal */
export function tableUid(pkg: Package, table: Table): Message {
  const [, engine] = calcEngine(pkg);
  const modelUuids = new Set([...uuidsIn(table.model), ...uuidsIn(table.archive)]);
  for (const r of engine.dependency_tracker.formula_owner_dependencies as Message[]) {
    const deps = pkg.get(r.identifier);
    if (has(deps, "base_owner_uid") && modelUuids.has(uuidValue(deps.formula_owner_uid))) return deps.base_owner_uid;
  }
  throw new Error("the table has no formula owners");
}

export interface AddTableOptions {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  /** Defaults to 1. */
  headerRows?: number;
  headerColumns?: number;
  /** One of the theme's six table styles. */
  style?: number;
  name?: string;
}

/** @internal */
export function addTable(slide: Slide, rows: CellValue[][], parts: Package, x: number, y: number, options: AddTableOptions): Table {
  const grid = toGrid(rows);
  const p = slide.pkg;
  const style = options.style ?? 0;
  const presets = themePresets(p).table_style_presets ?? [];
  if (!(Number.isInteger(style) && style >= 0 && style < presets.length)) {
    throw new Error(`style must be 0 to ${presets.length - 1}, one of the theme's table styles`);
  }
  const [root, donorInfo] = parts.objects("TST.TableInfoArchive").next().value as [number, Message];
  const donorSlide: number = donorInfo.super.parent.identifier;
  const donorModel = parts.deref(donorInfo.tableModel);
  const donorPresets = themePresets(parts).table_style_presets;
  const donorStyle = donorPresets.indexOf(donorModel.table_style_preset.identifier);

  // Table styles are named e.g. "table-0-tableStyle", "tableCell-0-bodyStyle".
  const rename = (name: string) => name.replace(new RegExp(`^(table\\w*)-${donorStyle}-`), `$1-${style}-`);
  const importer = new Importer(parts, p, rename, new Map([[donorPresets[donorStyle], presets[style]]]));
  const table = copyTable(importer, root, donorSlide, slide);
  const m = table.model;
  const tableCount = slide.presentation.slides.reduce((n, s) => n + s.tables.length, 0);
  m.table_name = options.name ?? `Table ${tableCount + 1}`;
  m.number_of_header_rows = 0;
  m.number_of_header_columns = 0;
  m.number_of_footer_rows = 0;
  const pos = table.info.geometry.position;
  pos.x = Number(x);
  pos.y = Number(y);
  table.resize(grid.length, grid[0].length);
  table.write(grid, new Map());
  table.setHeaders({ rows: Math.min(options.headerRows ?? 1, grid.length), columns: Math.min(options.headerColumns ?? 0, grid[0].length) });
  const columns = grid[0].length;
  const slideWidth = slide.presentation.size.width;
  const width = options.width ?? Math.min(x < slideWidth / 2 ? slideWidth - 2 * x : 1600.0, 300.0 * columns);
  const rowHeight = options.height === undefined ? 64.0 : options.height / grid.length;
  table.setColumnWidths(new Array(columns).fill(width / columns));
  table.setRowHeights(new Array(grid.length).fill(rowHeight));
  placeOnSlide(slide, table.identifier);
  return table;
}
