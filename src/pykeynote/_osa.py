"""Low-level bridge to Keynote through ``osascript``.

Values are never pasted into script source. JXA scripts get their arguments
as one JSON string in ``argv`` and return JSON. AppleScript scripts get plain
string arguments through ``on run argv``.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any, Sequence


class KeynoteError(RuntimeError):
    """Raised when Keynote or osascript reports an error."""


_JXA_WRAPPER = """
function run(argv) {
  const Keynote = Application("Keynote");
  const args = JSON.parse(argv[0]);
  const result = main(Keynote, args);
  return JSON.stringify(result === undefined ? null : result);
}
"""


def _execute(language: str, script: str, argv: Sequence[str]) -> str:
    """Run a script with osascript and return its stdout. Tests replace this."""
    try:
        proc = subprocess.run(
            ["osascript", "-l", language, "-", *argv],
            input=script,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise KeynoteError(
            "osascript was not found. pykeynote needs macOS with Keynote installed."
        ) from exc
    if proc.returncode != 0:
        raise KeynoteError(proc.stderr.strip() or f"osascript exited with {proc.returncode}")
    return proc.stdout


def jxa(script: str, **args: Any) -> Any:
    """Run a JXA script that defines ``function main(Keynote, args)``."""
    out = _execute("JavaScript", script + _JXA_WRAPPER, [json.dumps(args)])
    out = out.strip()
    return json.loads(out) if out else None


def applescript(script: str, *args: str) -> str:
    """Run an AppleScript with an ``on run argv`` handler and return its output."""
    return _execute("AppleScript", script, [str(a) for a in args]).strip()
