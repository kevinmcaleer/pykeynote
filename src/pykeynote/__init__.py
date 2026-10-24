"""Create, read and edit Apple Keynote presentations from Python.

:class:`Presentation` reads ``.key`` files directly, so Keynote isn't needed."""

from .builds import Build
from .charts import CHART_TYPES, Chart
from .document import Presentation, Slide, Transition, themes
from .drawables import SHAPE_KINDS, Drawable, Shape
from .tables import Table
from .media import Image
from .movies import Movie
from .markdown import from_markdown, parse_markdown
from .text import Paragraph, UnsupportedTextError

__all__ = ["Build", "CHART_TYPES", "Chart", "Drawable", "Image", "Movie", "SHAPE_KINDS", "Shape", "Table", "Paragraph", "Presentation", "Slide", "Transition", "UnsupportedTextError", "from_markdown", "parse_markdown", "themes"]
__version__ = "0.5.0"
