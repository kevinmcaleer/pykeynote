"""Charts: read a chart's type and data, change its data, and add new charts.

A chart is a ``TSCH.ChartDrawableArchive`` whose ``TSCH.ChartArchive``
extension holds the chart type and its data, a grid of row and column names
and values. The chart's look comes from one of the theme's six chart
presets (``TSCH.ChartStylePreset``), whose styles the chart refers to
directly. Its per-chart settings live in ``TSCH.*NonStyleArchive`` objects
in ``Index/ObjectContainer.iwa``.

New charts are copied from a small bundled deck that Keynote made (see
:mod:`pykeynote.clone`), with its styles swapped for the same-named styles
of the target deck's theme.
"""

from __future__ import annotations

import os
import re
import uuid as uuidlib
from typing import TYPE_CHECKING, Any, List, Optional, Sequence, Union

from .drawables import Drawable, place_on_slide
from .package import Package

if TYPE_CHECKING:
    from .document import Slide

Number = Union[int, float]

# Our names for Keynote's chart types (TSCH.ChartType).
CHART_TYPES = {
    "bar": "barChartType2D",  # horizontal bars
    "column": "columnChartType2D",  # vertical bars
    "stacked bar": "stackedBarChartType2D",
    "stacked column": "stackedColumnChartType2D",
    "line": "lineChartType2D",
    "area": "areaChartType2D",
    "stacked area": "stackedAreaChartType2D",
    "pie": "pieChartType2D",
    "donut": "donutChartType2D",
    "scatter": "scatterChartType2D",
}
_TYPE_NAMES = {v: k for k, v in CHART_TYPES.items()}
_BY_ROW, _BY_COLUMN = 1, 2  # TSCH.SeriesDirection
_LEGEND_GAP = 40.0  # points between the legend's bottom and the plot's top
_AXIS_ROOM = 48.0  # Keynote draws axis labels outside the plot, to its left and below it

# Which chart in the bundled parts deck to copy for each type.
_DONOR_FOR = {
    "bar": "column",
    "column": "column",
    "stacked bar": "column",
    "stacked column": "column",
    "line": "line",
    "area": "line",
    "stacked area": "line",
    "pie": "pie",
    "donut": "pie",
    "scatter": "line",
}


def _chart_ext(drawable: Any) -> Any:
    for field in drawable.Extensions:
        if field.full_name == "TSCH.ChartArchive.unity":
            return drawable.Extensions[field]
    raise ValueError("not a chart")


class Chart(Drawable):
    """A chart on a slide."""

    kind = "chart"

    @property
    def _chart(self) -> Any:
        return _chart_ext(self._archive)

    @property
    def chart_type(self) -> str:
        """``"column"``, ``"bar"``, ``"line"``, ``"pie"`` and so on (see :data:`CHART_TYPES`)."""
        c = self._chart
        name = c.DESCRIPTOR.fields_by_name["chart_type"].enum_type.values_by_number[c.chart_type].name
        return _TYPE_NAMES.get(name, name)

    @chart_type.setter
    def chart_type(self, value: str) -> None:
        if value not in CHART_TYPES:
            raise ValueError(f"chart type must be one of {', '.join(CHART_TYPES)}, not {value!r}")
        c = self._chart
        c.chart_type = c.DESCRIPTOR.fields_by_name["chart_type"].enum_type.values_by_name[CHART_TYPES[value]].number
        self._changed()

    @property
    def row_names(self) -> List[str]:
        return list(self._chart.grid.row_name)

    @property
    def column_names(self) -> List[str]:
        return list(self._chart.grid.column_name)

    @property
    def data(self) -> List[List[Optional[float]]]:
        """Values row by row. A missing value is ``None``."""
        rows = []
        for row in self._chart.grid.grid_row:
            rows.append([v.numeric_value if v.HasField("numeric_value") else None for v in row.value])
        return rows

    @property
    def series_by(self) -> str:
        """``"row"`` if each row is a data series (Keynote's default from AppleScript), else ``"column"``."""
        return "column" if self._chart.series_direction == _BY_COLUMN else "row"

    @series_by.setter
    def series_by(self, value: str) -> None:
        if value not in ("row", "column"):
            raise ValueError("series_by must be 'row' or 'column'")
        self._chart.series_direction = _BY_ROW if value == "row" else _BY_COLUMN
        self._changed()

    @property
    def series(self) -> List[str]:
        """Names of the data series, from the rows or columns depending on :attr:`series_by`."""
        return self.row_names if self.series_by == "row" else self.column_names

    def set_data(
        self,
        rows: Sequence[Sequence[Optional[Number]]],
        row_names: Sequence[str],
        column_names: Sequence[str],
    ) -> None:
        """Replace the chart's data: one list of values per row, ``None`` for a missing value."""
        if len(rows) != len(row_names):
            raise ValueError(f"{len(rows)} rows of data but {len(row_names)} row names")
        for i, row in enumerate(rows):
            if len(row) != len(column_names):
                raise ValueError(f"row {i} has {len(row)} values but there are {len(column_names)} column names")
        grid = self._chart.grid
        grid.Clear()
        grid.row_name.extend(str(n) for n in row_names)
        grid.column_name.extend(str(n) for n in column_names)
        for row in rows:
            r = grid.grid_row.add()
            for value in row:
                v = r.value.add()
                if value is not None:
                    v.numeric_value = float(value)
        for index in range(len(row_names)):
            grid.idMap.row_id_map.add(uniqueId=str(uuidlib.uuid4()).upper(), index=index)
        for index in range(len(column_names)):
            grid.idMap.column_id_map.add(uniqueId=str(uuidlib.uuid4()).upper(), index=index)
        self._chart.contains_default_data = False
        self._changed()

    def _settings(self) -> Any:
        """The chart's own settings (``TSCH.Generated.ChartNonStyleArchive``)."""
        archive = self._package.deref(self._chart.chart_non_style)
        for field in archive.Extensions:
            if field.full_name == "TSCH.Generated.ChartNonStyleArchive.current":
                return archive.Extensions[field]
        raise ValueError("chart has no settings")

    def _set_setting(self, name: str, value: bool) -> None:
        setattr(self._settings(), name, value)
        self._package.mark_changed(self._chart.chart_non_style.identifier)
        self.slide._touched()

    @property
    def show_legend(self) -> bool:
        return bool(self._settings().tschchartinfodefaultshowlegend)

    @show_legend.setter
    def show_legend(self, value: bool) -> None:
        self._set_setting("tschchartinfodefaultshowlegend", bool(value))

    @property
    def show_title(self) -> bool:
        return bool(self._settings().tschchartinfodefaultshowtitle)

    @show_title.setter
    def show_title(self, value: bool) -> None:
        self._set_setting("tschchartinfodefaultshowtitle", bool(value))

    def _resized(self) -> None:
        self._place_legend()

    def _place_legend(self) -> None:
        """Centre the legend just above the plot.

        The chart's geometry is its plot area, and the legend's frame is an
        offset from the plot's centre, so it moves with the chart.
        """
        width, height = self.size
        frame = self._chart.legend_frame
        frame.size.width = min(frame.size.width or 780.0, width)
        frame.origin.x = -frame.size.width / 2
        frame.origin.y = -height / 2 - _LEGEND_GAP - frame.size.height

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update(
            chart_type=self.chart_type,
            series_by=self.series_by,
            row_names=self.row_names,
            column_names=self.column_names,
            data=self.data,
        )
        return d


PARTS_DECK = os.path.join(os.path.dirname(__file__), "templates", "parts", "basic-white-parts.key")
_parts: Optional[Package] = None


def parts_package() -> Package:
    """The bundled deck that new charts and tables are copied from. Never saved."""
    global _parts
    if _parts is None:
        _parts = Package.open(PARTS_DECK)
    return _parts


def _donor_chart(donor: Package, chart_type: str) -> Any:
    from .clone import theme_presets

    want = CHART_TYPES[_DONOR_FOR[chart_type]]
    for identifier, obj in donor.objects("TSCH.ChartDrawableArchive"):
        c = _chart_ext(obj)
        name = c.DESCRIPTOR.fields_by_name["chart_type"].enum_type.values_by_number[c.chart_type].name
        if name == want:
            preset_index = theme_presets(donor)["chart_presets"].index(c.preset.identifier)
            return identifier, obj.super.parent.identifier, preset_index
    raise ValueError(f"no {chart_type} chart to copy from")


def copy_chart(importer: Any, root: int, src_slide_id: int, slide: "Slide") -> Chart:
    """Copy the chart ``root`` from the importer's source package onto ``slide``. It isn't placed on the slide."""
    id_map = importer.copy_drawable(root, src_slide_id, slide._slide_id)
    return Chart(slide, id_map[root])


def add_chart(
    slide: "Slide",
    chart_type: str,
    rows: Sequence[Sequence[Optional[Number]]],
    row_names: Sequence[str],
    column_names: Sequence[str],
    x: float,
    y: float,
    width: float,
    height: float,
    style: int = 0,
    series_by: Optional[str] = None,
    legend: Optional[bool] = None,
) -> Chart:
    from .clone import Importer, theme_presets

    round_chart = chart_type in ("pie", "donut")
    if series_by is None:
        # A pie shows the first value of each series, so its slices are best taken from the columns.
        series_by = "column" if round_chart else "row"
    if chart_type not in CHART_TYPES:
        raise ValueError(f"chart type must be one of {', '.join(CHART_TYPES)}, not {chart_type!r}")
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be more than 0")
    series = len(row_names) if series_by == "row" else len(column_names)
    if legend is None:
        legend = series > 1
    p = slide._package
    presets = theme_presets(p).get("chart_presets", [])
    if not 0 <= style < len(presets):
        raise ValueError(f"style must be 0 to {len(presets) - 1}, one of the theme's chart styles")
    donor = parts_package()
    root, donor_slide, donor_style = _donor_chart(donor, chart_type)

    def rename(name: str) -> str:
        return re.sub(rf"^chart-{donor_style}-", f"chart-{style}-", name)

    importer = Importer(donor, p, rename=rename, presets={theme_presets(donor)["chart_presets"][donor_style]: presets[style]})
    chart = copy_chart(importer, root, donor_slide, slide)
    if legend:
        # The legend sits above the plot, inside the box we were given.
        room = chart._chart.legend_frame.size.height + _LEGEND_GAP
        if height > 2 * room:
            y, height = y + room, height - room
    if not round_chart and width > 3 * _AXIS_ROOM and height > 3 * _AXIS_ROOM:
        # Leave room inside the box for the axis labels.
        x, width, height = x + _AXIS_ROOM, width - _AXIS_ROOM, height - _AXIS_ROOM
    if round_chart:
        # Keynote keeps pies square; centre the square in the box.
        side = min(width, height)
        x, width = x + (width - side) / 2, side
        height = side
    g = chart._info.geometry
    g.position.x, g.position.y = float(x), float(y)
    g.size.width, g.size.height = float(width), float(height)
    chart._place_legend()
    chart.chart_type = chart_type
    chart.series_by = series_by
    chart.set_data(rows, row_names, column_names)
    chart.show_legend = legend
    place_on_slide(slide, chart.identifier)
    return chart
