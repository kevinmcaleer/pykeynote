/**
 * Create, read and edit Apple Keynote presentations from JavaScript and
 * TypeScript. keynotejs reads and writes ``.key`` files directly, so it runs
 * anywhere JavaScript does, in Node or a browser, without Keynote or a Mac.
 */

export {
  Presentation,
  Slide,
  themes,
  type AddShapeOptions,
  type AddSlideOptions,
  type ApplyStyleOptions,
  type ApplyThemeOptions,
  type Aspect,
  type CreateOptions,
  type FrameOptions,
  type StyleBuild,
  type StyleTransition,
  type Transition,
  type TransitionOptions,
} from "./document.js";
export {
  DELIVERY_NAMES,
  DIRECTIONS,
  EFFECT_ALIASES,
  STARTS,
  type Build,
  type BuildOptions,
  type BuildTarget,
  type Direction,
  type Start,
} from "./builds.js";
export { CHART_TYPES, Chart, type AddChartOptions, type ChartType } from "./charts.js";
export { Drawable, SHAPE_KINDS, Shape, parseColor, type Color, type DrawableJSON, type ShapeKind } from "./drawables.js";
export { imageFormat, type AddImageOptions, type Image, type ImageSource, type ImageTarget } from "./media.js";
export {
  defaultLayout,
  fromMarkdown,
  parseMarkdown,
  slideToMarkdown,
  tableToMarkdown,
  toMarkdown,
  type FromMarkdownOptions,
  type ImageSpec,
  type SlideSpec,
  type TableSpec,
  type ToMarkdownOptions,
} from "./markdown.js";
export { Package } from "./package.js";
export { KEYNOTE_VERSION } from "./protobuf.js";
export { Table, type AddTableOptions, type CellValue } from "./tables.js";
export { preload, setTemplateLoader, type TemplateLoader } from "./templates.js";
export { Text, UnsupportedTextError, type Paragraph, type ParagraphInput } from "./text.js";
