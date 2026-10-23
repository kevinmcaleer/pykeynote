"""The ``pykeynote`` command: read and edit Keynote decks from a shell.

Every command takes ``--json`` to print the result as JSON for scripts and
LLM agents. ``pykeynote mcp`` starts the MCP server instead.
"""

from __future__ import annotations

import argparse
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
        return tools.add_build(args.deck, args.index, args.target, args.effect, args.delivery,
                               args.duration, args.kind, args.output)
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
    cp.add_argument("--target", default="body", choices=["title", "body"])
    cp.add_argument("--effect", default="dissolve", help="e.g. dissolve, 'move in'")
    cp.add_argument("--delivery", choices=["all at once", "by bullet"])
    cp.add_argument("--duration", type=float, default=1.0)
    cp.add_argument("--kind", default="in", choices=["in", "out"])
    cp.add_argument("--clear", action="store_true", help="remove the slide's builds instead")

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
