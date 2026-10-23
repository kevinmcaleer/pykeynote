/**
 * Create, read and edit Apple Keynote presentations from JavaScript and
 * TypeScript. keynotejs reads and writes ``.key`` files directly, so it runs
 * anywhere Node does, without Keynote or a Mac.
 */

export {
  Presentation,
  Slide,
  themes,
  type AddSlideOptions,
  type Aspect,
  type CreateOptions,
  type Transition,
  type TransitionOptions,
} from "./document.js";
export { defaultLayout, fromMarkdown, parseMarkdown, slideToMarkdown, toMarkdown, type FromMarkdownOptions, type SlideSpec } from "./markdown.js";
export { Package } from "./package.js";
export { KEYNOTE_VERSION } from "./protobuf.js";
export { Text, UnsupportedTextError, type Paragraph, type ParagraphInput } from "./text.js";

