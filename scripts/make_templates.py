"""Make the seed templates in src/pykeynote/templates with Keynote 14.5.

Run on a Mac with Keynote 14.5 installed:

    python scripts/make_templates.py --list
    python scripts/make_templates.py "Basic Black" "Gradient"

For each theme this writes ``<theme>-16x9.key`` (1920 x 1080) and
``<theme>-4x3.key`` (1024 x 768). Each template has one slide per master
slide, in master order, with sample title, body and notes text, which
``Presentation.new`` keeps hidden as models for ``add_slide``.

Keynote 14.5 is targeted by its bundle id, because ``tell application
"Keynote"`` can open a newer Keynote installed alongside it.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

KEYNOTE = "com.apple.iWork.Keynote"
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "..", "src", "pykeynote", "templates")
SIZES = {"16x9": (1920, 1080), "4x3": (1024, 768)}

LIST_THEMES = f"""
tell application id "{KEYNOTE}"
  set out to ""
  repeat with t in themes
    set out to out & (name of t) & linefeed
  end repeat
  return out
end tell
"""

MAKE_TEMPLATE = f"""
on run argv
  set themeName to item 1 of argv
  set w to (item 2 of argv) as integer
  set h to (item 3 of argv) as integer
  set outPath to item 4 of argv
  tell application id "{KEYNOTE}"
    set d to make new document with properties {{document theme:theme themeName, width:w, height:h}}
    if width of d is not w or height of d is not h then
      set width of d to w
      set height of d to h
    end if
    set firstSlide to slide 1 of d
    repeat with m in master slides of d
      set mName to (name of m) as text
      set s to make new slide at end of slides of d with properties {{base slide:m}}
      tell s
        if title showing then set object text of default title item to mName
        if body showing then set object text of default body item to "First bullet" & linefeed & "Second bullet" & linefeed & "Third bullet"
        set presenter notes to "Notes for " & mName
      end tell
    end repeat
    delete firstSlide
    save d in POSIX file outPath
    close d saving no
  end tell
end run
"""


def osascript(script: str, *args: str) -> str:
    proc = subprocess.run(["osascript", "-", *args], input=script, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(proc.stderr.strip())
    return proc.stdout


def slug(theme: str) -> str:
    return theme.strip().lower().replace(" ", "-")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("themes", nargs="*", help="theme names, as Keynote lists them")
    parser.add_argument("--list", action="store_true", help="list Keynote's themes and exit")
    parser.add_argument("--out", default=TEMPLATES_DIR, help="folder to write the templates to")
    args = parser.parse_args()
    if args.list or not args.themes:
        print(osascript(LIST_THEMES).strip())
        return
    for theme in args.themes:
        for aspect, (w, h) in SIZES.items():
            path = os.path.abspath(os.path.join(args.out, f"{slug(theme)}-{aspect}.key"))
            if os.path.exists(path):
                os.remove(path)
            osascript(MAKE_TEMPLATE, theme, str(w), str(h), path)
            print(f"{path}  {os.path.getsize(path) // 1024} KB")


if __name__ == "__main__":
    main()
