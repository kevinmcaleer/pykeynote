"""Create, read and edit Apple Keynote presentations from Python.

:class:`Presentation` reads ``.key`` files directly, so Keynote isn't needed.
The older :mod:`pykeynote.scripting` module drives a running copy of Keynote
on a Mac instead, and will go once the file-based engine can do everything
it does.
"""

from ._osa import KeynoteError
from .builds import Build
from .document import Presentation, Slide, Transition, themes
from .markdown import from_markdown, parse_markdown
from .text import Paragraph, UnsupportedTextError

__all__ = ["Build", "KeynoteError", "Paragraph", "Presentation", "Slide", "Transition", "UnsupportedTextError", "from_markdown", "parse_markdown", "themes"]
__version__ = "0.2.0"
