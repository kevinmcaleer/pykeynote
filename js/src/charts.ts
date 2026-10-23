/**
 * Charts: read a chart's type and data, change its data, and add new charts.
 *
 * A chart is a ``TSCH.ChartDrawableArchive`` whose ``TSCH.ChartArchive``
 * extension holds the chart type and its data, a grid of row and column names
 * and values. The chart's look comes from one of the theme's six chart
 * presets (``TSCH.ChartStylePreset``), whose styles the chart refers to
 * directly. Its per-chart settings live in ``TSCH.*NonStyleArchive`` objects
 * in ``Index/ObjectContainer.iwa``.
 *
 * New charts are copied from a small bundled deck that Keynote made (see
 * ``clone.ts``), with its styles swapped for the same-named styles of the
 * target deck's theme.
 */

import { Importer, themePresets } from "./clone.js";
import type { Slide } from "./document.js";
import { Drawable, placeOnSlide, type DrawableJSON } from "./drawables.js";
import { newUuidParts, type Package } from "./package.js";
import { create, enumValue, ensure, has, type Message } from "./protobuf.js";

/** Our names for Keynote's chart types (``TSCH.ChartType``). */
export const CHART_TYPES = {
  bar: "barChartType2D", // horizontal bars
  column: "columnChartType2D", // vertical bars
  "stacked bar": "stackedBarChartType2D",
  "stacked column": "stackedColumnChartType2D",
  line: "lineChartType2D",
  area: "areaChartType2D",
  "stacked area": "stackedAreaChartType2D",
  pie: "pieChartType2D",
  donut: "donutChartType2D",
  scatter: "scatterChartType2D",
} as const;
export type ChartType = keyof typeof CHART_TYPES;

const CHART_EXTENSION = "TSCH.ChartArchive.unity";
const SETTINGS_EXTENSION = "TSCH.Generated.ChartNonStyleArchive.current";
const CHART_TYPE_ENUM = "TSCH.ChartType";
const BY_ROW = 1, BY_COLUMN = 2; // TSCH.SeriesDirection
const LEGEND_GAP = 40.0; // points between the legend's bottom and the plot's top
const AXIS_ROOM = 48.0; // Keynote draws axis labels outside the plot, to its left and below it

// Which chart in the bundled parts deck to copy for each type.
const DONOR_FOR: Record<ChartType, ChartType> = {
  bar: "column",
  column: "column",
  "stacked bar": "column",
  "stacked column": "column",
  line: "line",
  area: "line",
  "stacked area": "line",
  pie: "pie",
  donut: "pie",
  scatter: "line",
};

function chartExtension(drawable: Message): Message {
  if (!has(drawable, CHART_EXTENSION)) throw new Error("not a chart");
  return drawable[CHART_EXTENSION];
}

function typeName(value: number): string {
  const found = Object.entries(CHART_TYPES).find(([, v]) => enumValue(CHART_TYPE_ENUM, v) === value);
  return found ? found[0] : String(value);
}

function uuidString(): string {
  const [lower, upper] = newUuidParts().map((v) => BigInt(v));
  const hex = ((upper << 64n) | lower).toString(16).padStart(32, "0").toUpperCase();
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/** A chart on a slide. */
export class Chart extends Drawable {
  override get kind(): string {
    return "chart";
  }

  private get chart(): Message {
    return chartExtension(this.archive);
  }

  /** ``"column"``, ``"bar"``, ``"line"``, ``"pie"`` and so on (see {@link CHART_TYPES}). */
  get chartType(): string {
    return typeName(this.chart.chart_type);
  }

  set chartType(value: string) {
    if (!(value in CHART_TYPES)) throw new Error(`chart type must be one of ${Object.keys(CHART_TYPES).join(", ")}, not ${JSON.stringify(value)}`);
    this.chart.chart_type = enumValue(CHART_TYPE_ENUM, CHART_TYPES[value as ChartType]);
    this.changed();
  }

  get rowNames(): string[] {
    return [...(this.chart.grid?.row_name ?? [])];
  }

  get columnNames(): string[] {
    return [...(this.chart.grid?.column_name ?? [])];
  }

  /** Values row by row. A missing value is ``null``. */
  get data(): (number | null)[][] {
    return ((this.chart.grid?.grid_row ?? []) as Message[]).map((row) =>
      (row.value as Message[]).map((v) => (has(v, "numeric_value") ? v.numeric_value : null)),
    );
  }

  /** ``"row"`` if each row is a data series (Keynote's default from AppleScript), else ``"column"``. */
  get seriesBy(): "row" | "column" {
    return this.chart.series_direction === BY_COLUMN ? "column" : "row";
  }

  set seriesBy(value: "row" | "column") {
    if (value !== "row" && value !== "column") throw new Error('seriesBy must be "row" or "column"');
    this.chart.series_direction = value === "row" ? BY_ROW : BY_COLUMN;
    this.changed();
  }

  /** Names of the data series, from the rows or columns depending on {@link seriesBy}. */
  get series(): string[] {
    return this.seriesBy === "row" ? this.rowNames : this.columnNames;
  }

  /** Replace the chart's data: one list of values per row, ``null`` for a missing value. */
  setData(rows: (number | null)[][], rowNames: string[], columnNames: string[]): void {
    if (rows.length !== rowNames.length) throw new Error(`${rows.length} rows of data but ${rowNames.length} row names`);
    rows.forEach((row, i) => {
      if (row.length !== columnNames.length) {
        throw new Error(`row ${i} has ${row.length} values but there are ${columnNames.length} column names`);
      }
    });
    const grid = create("TSCH.ChartGridArchive", {
      row_name: rowNames.map(String),
      column_name: columnNames.map(String),
      grid_row: rows.map((row) =>
        create("TSCH.GridRow", {
          value: row.map((value) =>
            value === null || value === undefined
              ? create("TSCH.GridValue")
              : create("TSCH.GridValue", { numeric_value: Number(value) }),
          ),
        }),
      ),
      idMap: create("TSCH.ChartGridArchive.ChartGridRowColumnIdMap", {
        row_id_map: rowNames.map((_, index) => create("TSCH.ChartGridArchive.ChartGridRowColumnIdMap.Entry", { uniqueId: uuidString(), index })),
        column_id_map: columnNames.map((_, index) => create("TSCH.ChartGridArchive.ChartGridRowColumnIdMap.Entry", { uniqueId: uuidString(), index })),
      }),
    });
    this.chart.grid = grid;
    this.chart.contains_default_data = false;
    this.changed();
  }

  /** The chart's own settings (``TSCH.Generated.ChartNonStyleArchive``). */
  private settings(): Message {
    const archive = this.pkg.deref(this.chart.chart_non_style);
    if (!has(archive, SETTINGS_EXTENSION)) throw new Error("chart has no settings");
    return archive[SETTINGS_EXTENSION];
  }

  private setSetting(name: string, value: boolean): void {
    this.settings()[name] = value;
    this.pkg.markChanged(this.chart.chart_non_style.identifier);
    this.slide.touched();
  }

  get showLegend(): boolean {
    return Boolean(this.settings().tschchartinfodefaultshowlegend);
  }

  set showLegend(value: boolean) {
    this.setSetting("tschchartinfodefaultshowlegend", Boolean(value));
  }

  get showTitle(): boolean {
    return Boolean(this.settings().tschchartinfodefaultshowtitle);
  }

  set showTitle(value: boolean) {
    this.setSetting("tschchartinfodefaultshowtitle", Boolean(value));
  }

  override resized(): void {
    this.placeLegend();
  }

  /** @internal Centre the legend just above the plot. The legend's frame is an offset from the plot's centre. */
  placeLegend(): void {
    const [width, height] = this.size;
    const frame = ensure(this.chart, "legend_frame");
    const size = ensure(frame, "size");
    const origin = ensure(frame, "origin");
    size.width = Math.min(size.width || 780.0, width);
    origin.x = -size.width / 2;
    origin.y = -height / 2 - LEGEND_GAP - size.height;
  }

  /** @internal */
  get legendHeight(): number {
    return this.chart.legend_frame?.size?.height ?? 0;
  }

  override toJSON(): DrawableJSON {
    return {
      ...super.toJSON(),
      chartType: this.chartType,
      seriesBy: this.seriesBy,
      rowNames: this.rowNames,
      columnNames: this.columnNames,
      data: this.data,
    };
  }
}

function donorChart(donor: Package, chartType: ChartType): [number, number, number] {
  const want = enumValue(CHART_TYPE_ENUM, CHART_TYPES[DONOR_FOR[chartType]]);
  for (const [identifier, obj] of donor.objects("TSCH.ChartDrawableArchive")) {
    const c = chartExtension(obj);
    if (c.chart_type === want) {
      const presetIndex = themePresets(donor).chart_presets.indexOf(c.preset.identifier);
      return [identifier, obj.super.parent.identifier, presetIndex];
    }
  }
  throw new Error(`no ${chartType} chart to copy from`);
}

/** @internal Copy the chart ``root`` from the importer's source package onto ``slide``. It isn't placed on the slide. */
export function copyChart(importer: Importer, root: number, srcSlideId: number, slide: Slide): Chart {
  const idMap = importer.copyDrawable(root, srcSlideId, slide.slideId);
  return new Chart(slide, idMap.get(root)!);
}

export interface AddChartOptions {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  /** One of the theme's six chart styles. */
  style?: number;
  /** ``"row"`` if each row is a series; defaults to ``"column"`` for pies and donuts. */
  seriesBy?: "row" | "column";
  /** Defaults to showing a legend when there's more than one series. */
  legend?: boolean;
}

/** @internal */
export function addChart(
  slide: Slide,
  chartType: string,
  rows: (number | null)[][],
  rowNames: string[],
  columnNames: string[],
  parts: Package,
  frame: [number, number, number, number],
  options: AddChartOptions,
): Chart {
  let [x, y, width, height] = frame;
  if (!(chartType in CHART_TYPES)) {
    throw new Error(`chart type must be one of ${Object.keys(CHART_TYPES).join(", ")}, not ${JSON.stringify(chartType)}`);
  }
  const type = chartType as ChartType;
  const roundChart = type === "pie" || type === "donut";
  // A pie shows the first value of each series, so its slices are best taken from the columns.
  const seriesBy = options.seriesBy ?? (roundChart ? "column" : "row");
  if (!(width > 0 && height > 0)) throw new Error("width and height must be more than 0");
  const series = seriesBy === "row" ? rowNames.length : columnNames.length;
  const legend = options.legend ?? series > 1;
  const p = slide.pkg;
  const style = options.style ?? 0;
  const presets = themePresets(p).chart_presets ?? [];
  if (!(Number.isInteger(style) && style >= 0 && style < presets.length)) {
    throw new Error(`style must be 0 to ${presets.length - 1}, one of the theme's chart styles`);
  }
  const [root, donorSlide, donorStyle] = donorChart(parts, type);
  const rename = (name: string) => name.replace(new RegExp(`^chart-${donorStyle}-`), `chart-${style}-`);
  const donorPresets = themePresets(parts).chart_presets;
  const importer = new Importer(parts, p, rename, new Map([[donorPresets[donorStyle], presets[style]]]));
  const chart = copyChart(importer, root, donorSlide, slide);
  if (legend) {
    // The legend sits above the plot, inside the box we were given.
    const room = chart.legendHeight + LEGEND_GAP;
    if (height > 2 * room) [y, height] = [y + room, height - room];
  }
  if (!roundChart && width > 3 * AXIS_ROOM && height > 3 * AXIS_ROOM) {
    // Leave room inside the box for the axis labels.
    [x, width, height] = [x + AXIS_ROOM, width - AXIS_ROOM, height - AXIS_ROOM];
  }
  if (roundChart) {
    // Keynote keeps pies square; centre the square in the box.
    const side = Math.min(width, height);
    [x, width, height] = [x + (width - side) / 2, side, side];
  }
  const g = ensure(chart.info, "geometry");
  Object.assign(ensure(g, "position"), { x: Number(x), y: Number(y) });
  Object.assign(ensure(g, "size"), { width: Number(width), height: Number(height) });
  chart.placeLegend();
  chart.chartType = type;
  chart.seriesBy = seriesBy;
  chart.setData(rows, rowNames, columnNames);
  chart.showLegend = legend;
  placeOnSlide(slide, chart.identifier);
  return chart;
}
