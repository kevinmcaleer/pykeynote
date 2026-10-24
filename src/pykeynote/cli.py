"""The ``pykeynote`` command: read and edit Keynote decks from a shell.

Every command takes ``--json`` to print the result as JSON for scripts and
LLM agents. ``pykeynote mcp`` starts the MCP server instead.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from typing import Any, Dict, List, Optional, Sequence

from . import __version__, tools


def _body(lines: Optional[List[str]]) -> Optional[List[Dict[str, Any]]]:
    """Turn ``--body`` values into paragraphs. Two leading spaces per indent level."""
    if lines is None:
        return None
    out = []
    for value in lines:
        for line in value.split("\n"):
            stripped = line.lstrip(" ")
            out.append({"text": stripped, "level": (len(line) - len(stripped)) // 2})
    return out


def _read(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8") as f:
        return f.read()


def _target(value: str) -> Any:
    """A build or image target: an id from ``show --json``, or a name such as body or Media."""
    return int(value) if value.lstrip("-").isdigit() else value


def _cell(value: str) -> Any:
    v = value.strip()
    if v == "":
        return None
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    for kind in (int, float):
        try:
            return kind(v)
        except ValueError:
            pass
    return value


def _grid(args: argparse.Namespace) -> List[List[Any]]:
    """Rows from ``--csv FILE`` or repeated ``--row a,b,c``."""
    if args.csv:
        text = _read(args.csv)
    elif args.row:
        text = "\n".join(args.row)
    else:
        raise ValueError("give the cells with --csv FILE or --row a,b,c (repeat --row for each row)")
    return [[_cell(c) for c in row] for row in csv.reader(io.StringIO(text)) if row]


def _chart_data(grid: List[List[Any]]) -> Dict[str, Any]:
    """Split a grid whose first row holds the column names and first column the row names."""
    if len(grid) < 2 or len(grid[0]) < 2:
        raise ValueError("chart data needs a header row of column names and a first column of row names")
    return {
        "column_names": [str(c) for c in grid[0][1:]],
        "row_names": [str(r[0]) for r in grid[1:]],
        "rows": [[c if isinstance(c, (int, float)) and not isinstance(c, bool) else None for c in r[1:]] for r in grid[1:]],
    }


def _frame(args: argparse.Namespace) -> Dict[str, Any]:
    return {"x": args.x, "y": args.y, "width": args.width, "height": args.height}


def _print_slides(slides: List[Dict[str, Any]]) -> None:
    for s in slides:
        flag = "  (skipped)" if s.get("skipped") else ""
        print(f"{s['index']:>3}  {s['layout']:<22} {s['title'] or ''}{flag}")


def _print_info(info: Dict[str, Any]) -> None:
    size = info["size"]
    print(f"{info['path']}")
    print(f"theme: {info['theme']}, {size['width']} x {size['height']}, {info['slide_count']} slides")
    print(f"layouts: {', '.join(info['layouts'])}")
    print()
    _print_slides(info["slides"])


def _print_slide(s: Dict[str, Any]) -> None:
    print(f"slide {s['index']}  layout: {s['layout']}{'  (skipped)' if s['skipped'] else ''}")
    if s["title"] is not None:
        print(f"title: {s['title']}")
    if s["body"] is not None:
        print("body:")
        for p in s["paragraphs"]:
            print("  " + "  " * p["level"] + ("- " if p["bulleted"] else "") + p["text"])
    t = s["transition"]
    if t["effect"]:
        print(f"transition: {t['effect']} {t['duration']:g}s")
    for d in s["drawables"]:
        what = d.get("chart_type") or d.get("name") or (d.get("text") or "").split("\n")[0]
        print(f"{d['type']} (id {d['id']}): {what}  at {d['x']:g},{d['y']:g} size {d['width']:g}x{d['height']:g}")
    for i in s["images"]:
        x, y = i["position"]
        w, h = i["size"]
        what = i["placeholder"] and f"placeholder {i['placeholder']}" or i["filename"] or ""
        print(f"image (id {i['id']}): {what}  at {x:g},{y:g} size {w:g}x{h:g}")
    for m in s["movies"]:
        x, y = m["position"]
        w, h = m["size"]
        kind = "sound" if m["audio_only"] else "video"
        what = m["placeholder"] and f"placeholder {m['placeholder']}" or m["filename"] or ""
        print(f"{kind} (id {m['id']}): {what}  {m['duration']:g}s  at {x:g},{y:g} size {w:g}x{h:g}")
    for b in s["builds"]:
        print(f"build: {b['target']} {b['kind']}, {b['effect']}, {b['delivery']}, {b['duration']:g}s")
    if s["notes"]:
        print("notes:")
        for line in s["notes"].split("\n"):
            print("  " + line)


def _run(args: argparse.Namespace) -> Any:
    c = args.command
    if c == "themes":
        return tools.list_themes()
    if c == "info":
        return tools.deck_info(args.deck)
    if c == "show":
        return tools.read_slide(args.deck, args.index)
    if c == "export":
        return tools.export_markdown(args.deck, args.output)
    if c == "new":
        markdown = _read(args.markdown) if args.markdown else None
        return tools.create_deck(args.deck, markdown, args.theme, args.aspect, args.force)
    if c == "edit":
        skipped = None if args.skip is None else args.skip == "yes"
        return tools.edit_slide(args.deck, args.index, args.title, _body(args.body), args.notes, skipped,
                                args.transition, args.duration, args.output)
    if c == "add":
        return tools.add_slide(args.deck, args.layout, args.title, _body(args.body), args.notes, args.at, args.output)
    if c == "delete":
        return tools.delete_slide(args.deck, args.index, args.output)
    if c == "move":
        return tools.move_slide(args.deck, args.index, args.to, args.output)
    if c == "duplicate":
        return tools.duplicate_slide(args.deck, args.index, args.to, args.output)
    if c == "theme":
        layouts = dict(m.split("=", 1) for m in args.layout or [])
        return tools.apply_theme(args.deck, args.theme, args.aspect, layouts, args.output)
    if c == "build":
        if args.clear:
            return tools.clear_builds(args.deck, args.index, args.output)
        return tools.add_build(args.deck, args.index, _target(args.target), args.effect, args.delivery,
                               args.duration, args.kind, args.output)
    if c == "image":
        if args.replace is not None:
            return tools.replace_image(args.deck, args.index, _target(args.replace), args.file, args.alt, args.output)
        placeholder = False if args.no_placeholder else args.placeholder
        return tools.add_image(args.deck, args.index, args.file, description=args.alt, placeholder=placeholder,
                               output=args.output, **_frame(args))
    if c == "movie":
        placeholder = False if args.no_placeholder else args.placeholder
        return tools.add_movie(args.deck, args.index, args.file, description=args.alt, placeholder=placeholder,
                               loop=args.loop, volume=args.volume, poster=args.poster, output=args.output,
                               **_frame(args))
    if c == "shape":
        return tools.add_shape(args.deck, args.index, args.kind, _body(args.text), args.fill, args.style,
                               output=args.output, **_frame(args))
    if c == "textbox":
        return tools.add_text_box(args.deck, args.index, _body(args.text), output=args.output, **_frame(args))
    if c == "table":
        return tools.add_table(args.deck, args.index, _grid(args), args.header_rows, args.header_columns,
                               args.style, args.name, output=args.output, **_frame(args))
    if c == "chart":
        legend = None if args.legend is None else args.legend == "yes"
        return tools.add_chart(args.deck, args.index, args.type, series_by=args.series_by, legend=legend,
                               style=args.style, output=args.output, **_chart_data(_grid(args)), **_frame(args))
    if c == "remove":
        target = _target(args.target)
        slide = tools.read_slide(args.deck, args.index)
        if isinstance(target, int) and any(d["id"] == target for d in slide["drawables"]):
            return tools.delete_drawable(args.deck, args.index, target, args.output)
        if any(m["id"] == target or m["placeholder"] == target for m in slide["movies"]):
            return tools.remove_movie(args.deck, args.index, target, args.output)
        return tools.remove_image(args.deck, args.index, target, args.output)
    raise AssertionError(c)


def _show(args: argparse.Namespace, result: Any) -> None:
    c = args.command
    if c == "themes":
        print("\n".join(result["themes"]))
    elif c in ("info", "new", "theme"):
        _print_info(result)
    elif c == "export":
        if not result["output"]:
            sys.stdout.write(result["markdown"])
    elif c in ("delete", "move"):
        _print_slides(result["slides"])
    else:
        _print_slide(result)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pykeynote", description="Read and edit Apple Keynote .key files.")
    p.add_argument("--version", action="version", version=f"pykeynote {__version__}")
    sub = p.add_subparsers(dest="command", required=True, metavar="command")

    def command(name: str, help: str, deck: bool = True, index: bool = False, writes: bool = False):
        cp = sub.add_parser(name, help=help, description=help)
        if deck:
            cp.add_argument("deck", help="path to a .key file")
        if index:
            cp.add_argument("index", type=int, help="slide index, from 0 (negative counts from the end)")
        if writes:
            cp.add_argument("-o", "--output", help="save to this .key file instead of changing the deck in place")
        cp.add_argument("--json", action="store_true", help="print the result as JSON")
        return cp

    command("themes", "list the bundled themes for new decks", deck=False)
    command("info", "describe a deck and list its slides")
    command("show", "print one slide's text, notes, transition and builds", index=True)
    cp = command("export", "convert a deck to Markdown")
    cp.add_argument("-o", "--output", help="write the Markdown to this file")

    cp = command("new", "create a .key file, from Markdown if given")
    cp.add_argument("-m", "--markdown", metavar="FILE", help="Markdown file to build the deck from (- for stdin)")
    cp.add_argument("--theme", default="Basic White")
    cp.add_argument("--aspect", default="16:9", choices=["16:9", "4:3"])
    cp.add_argument("-f", "--force", action="store_true", help="replace the file if it exists")

    body_help = "body text; repeat for more paragraphs, two leading spaces per indent level"
    cp = command("edit", "change a slide's title, body, notes, transition or skipping", index=True, writes=True)
    cp.add_argument("--title")
    cp.add_argument("--body", action="append", help=body_help)
    cp.add_argument("--notes")
    cp.add_argument("--skip", choices=["yes", "no"], help="skip the slide when playing")
    cp.add_argument("--transition", help="e.g. dissolve, push, 'magic move' or none")
    cp.add_argument("--duration", type=float, help="transition duration in seconds")

    cp = command("add", "add a slide", writes=True)
    cp.add_argument("--layout", default="Title & Bullets", help="one of the deck's layouts (see info)")
    cp.add_argument("--title")
    cp.add_argument("--body", action="append", help=body_help)
    cp.add_argument("--notes")
    cp.add_argument("--at", type=int, help="position for the new slide (default: the end)")

    command("delete", "delete a slide", index=True, writes=True)
    cp = command("move", "move a slide", index=True, writes=True)
    cp.add_argument("to", type=int, help="where the slide ends up")
    cp = command("duplicate", "copy a slide", index=True, writes=True)
    cp.add_argument("--to", type=int, help="where the copy goes (default: right after)")

    cp = command("theme", "switch a deck to another bundled theme, keeping its content", writes=True)
    cp.add_argument("theme", help="a theme from 'pykeynote themes'")
    cp.add_argument("--aspect", choices=["16:9", "4:3"], help="default: the closer one to the current size")
    cp.add_argument("--layout", action="append", metavar="OLD=NEW", help="use layout NEW for slides on OLD")

    cp = command("build", "add a build animation to a slide, or clear them", index=True, writes=True)
    cp.add_argument("--target", default="body", help="title, body, or an object's id from 'show'")
    cp.add_argument("--effect", default="dissolve", help="e.g. dissolve, 'move in'")
    cp.add_argument("--delivery", choices=["all at once", "by bullet"])
    cp.add_argument("--duration", type=float, default=1.0)
    cp.add_argument("--kind", default="in", choices=["in", "out"])
    cp.add_argument("--clear", action="store_true", help="remove the slide's builds instead")

    def frame(cp: argparse.ArgumentParser) -> None:
        cp.add_argument("--x", type=float, help="left edge in points (default: centred)")
        cp.add_argument("--y", type=float, help="top edge in points (default: centred)")
        cp.add_argument("--width", type=float)
        cp.add_argument("--height", type=float)

    def cells(cp: argparse.ArgumentParser) -> None:
        cp.add_argument("--csv", metavar="FILE", help="CSV file of cells (- for stdin)")
        cp.add_argument("--row", action="append", help="one row of comma-separated cells; repeat for more rows")
        cp.add_argument("--style", type=int, default=0, choices=range(6), help="one of the theme's six styles")

    cp = command("image", "add a PNG, JPEG or GIF image, or replace one", index=True, writes=True)
    cp.add_argument("file", help="the image file")
    frame(cp)
    cp.add_argument("--alt", help="accessibility description")
    cp.add_argument("--placeholder", help="fill this media placeholder, e.g. Media-2")
    cp.add_argument("--no-placeholder", action="store_true", help="don't fill a media placeholder")
    cp.add_argument("--replace", metavar="TARGET", help="swap the picture in this image id or placeholder instead")

    cp = command("movie", "add a video or sound (.mp4, .m4v, .mov or .m4a)", index=True, writes=True)
    cp.add_argument("file", help="the video or sound file")
    frame(cp)
    cp.add_argument("--alt", help="accessibility description")
    cp.add_argument("--placeholder", help="fill this media placeholder, e.g. Media-2")
    cp.add_argument("--no-placeholder", action="store_true", help="don't fill a media placeholder")
    cp.add_argument("--loop", default="none", choices=["none", "repeat", "back and forth"])
    cp.add_argument("--volume", type=float, default=1.0, help="from 0 to 1")
    cp.add_argument("--poster", help="a PNG, JPEG or GIF shown before the video plays")

    cp = command("shape", "add a shape", index=True, writes=True)
    cp.add_argument("--kind", default="rectangle", help="e.g. rectangle, oval, star, arrow")
    cp.add_argument("--text", action="append", help=body_help)
    cp.add_argument("--fill", help="fill colour, e.g. '#3366ff' or red")
    cp.add_argument("--style", type=int, default=0, choices=range(6), help="one of the theme's six shape styles")
    frame(cp)

    cp = command("textbox", "add a text box", index=True, writes=True)
    cp.add_argument("text", nargs="+", help=body_help)
    frame(cp)

    cp = command("table", "add a table from CSV", index=True, writes=True)
    cells(cp)
    cp.add_argument("--header-rows", type=int, default=1)
    cp.add_argument("--header-columns", type=int, default=0)
    cp.add_argument("--name", help="the table's name")
    frame(cp)

    cp = command("chart", "add a chart from CSV: column names in the first row, row names in the first column",
                 index=True, writes=True)
    cp.add_argument("type", help="column, bar, line, area, pie, donut, scatter, or 'stacked column' etc.")
    cells(cp)
    cp.add_argument("--series-by", choices=["row", "column"])
    cp.add_argument("--legend", choices=["yes", "no"])
    frame(cp)

    cp = command("remove", "delete a shape, text box, table, chart, image, video or sound by its id from 'show'",
                 index=True, writes=True)
    cp.add_argument("target", help="the id, or a media placeholder tag such as Media")

    sub.add_parser("mcp", help="run the MCP server on stdin and stdout", description="Run the MCP server on stdio.")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "mcp":
        from .mcp import serve

        serve()
        return 0
    try:
        result = _run(args)
    except Exception as e:
        if args.json:
            print(json.dumps({"error": str(e), "type": type(e).__name__}))
        else:
            print(f"pykeynote: error: {e}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        _show(args, result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
