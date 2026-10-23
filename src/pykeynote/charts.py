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

import uuid as uuidlib
from typing import TYPE_CHECKING, Any, List, Optional, Sequence, Union

from .drawables import Drawable

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
