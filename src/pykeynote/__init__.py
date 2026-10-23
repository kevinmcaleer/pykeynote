"""Create, read and edit Apple Keynote presentations from Python."""

from ._osa import KeynoteError
from .presentation import Presentation, Slide, list_themes
from .transitions import EFFECTS, Transition

__all__ = ["EFFECTS", "KeynoteError", "Presentation", "Slide", "Transition", "list_themes"]
__version__ = "0.1.0"
