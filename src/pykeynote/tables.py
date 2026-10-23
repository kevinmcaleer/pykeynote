"""Tables: read and change cells, and add new tables.

A table is a ``TST.TableInfoArchive`` (its frame on the slide) pointing at a
``TST.TableModelArchive``, both kept in ``Index/CalculationEngine.iwa``.
The model's data store holds the cells in ``TST.Tile`` objects, one row of
up to 256 cells per ``TST.TileRowInfo``, each cell packed into a small
binary record. Text lives in a string list (``TST.TableDataList``) that
cells refer to by key, and each row and column has a header entry with its
height or width. Tiles, lists and headers are components of their own.

Each table is also several "formula owners" in the calculation engine,
which knows them by UUID and by a small internal number.

The cell record layout (storage version 5) follows numbers-parser's notes:
a 12-byte header (version, cell type, 2 unused bytes, 4 bytes, then 32 bits
of flags), then one field per flag in bit order. Flag 0x1 is a 16-byte
decimal, 0x2 and 0x4 are 8-byte doubles, every other flag is 4 bytes.

New tables are copied from a table that Keynote made, in the bundled parts
deck, then resized and filled.
"""

from __future__ import annotations

import datetime
import re
import struct
import uuid as uuidlib
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple, Union

from .drawables import Drawable, place_on_slide
from .package import Package, new_uuid_parts, walk_messages

if TYPE_CHECKING:
    from .document import Slide

Value = Union[None, str, int, float, bool]

_TILE_SIZE = 256
_EMPTY, _NUMBER, _TEXT, _DATE, _BOOL, _DURATION, _ERROR, _RICH = 0, 2, 3, 5, 6, 7, 8, 9

_DECIMAL, _DOUBLE, _SECONDS, _STRING, _RICH_ID = 0x1, 0x2, 0x4, 0x8, 0x10
_SUGGEST, _NUM_FORMAT, _TEXT_FORMAT, _BOOL_FORMAT = 0x1000, 0x2000, 0x20000, 0x40000
_FORMAT_FLAGS = (0x2000, 0x4000, 0x8000, 0x10000, 0x20000, 0x40000)
_STYLE_FLAGS = (0x20, 0x40)
_VALUE_FLAGS = _DECIMAL | _DOUBLE | _SECONDS | _STRING | _RICH_ID
_EPOCH = datetime.datetime(2001, 1, 1)

# Keynote 14.5 marks a text cell with suggest 5 and a number with suggest 1.
_SUGGEST_TEXT, _SUGGEST_NUMBER = 5, 1
# Format types (TSK.FormatStructArchive.format_type) for plain text and numbers.
_FORMAT_TEXT, _FORMAT_NUMBER = 260, 256


def _field_size(flag: int) -> int:
    return 16 if flag == _DECIMAL else 8 if flag in (_DOUBLE, _SECONDS) else 4


# --- decimals -----------------------------------------------------------------


def unpack_decimal128(b: bytes) -> float:
    exponent = (((b[15] & 0x7F) << 7) | (b[14] >> 1)) - 0x1820
    mantissa = b[14] & 1
    for i in range(13, -1, -1):
        mantissa = mantissa * 256 + b[i]
    value = mantissa * 10.0**exponent if exponent < 0 else float(mantissa * 10**exponent)
    return -value if b[15] & 0x80 else value


def pack_decimal128(value: float) -> bytes:
    text = repr(float(value)) if not isinstance(value, int) else str(value)
    sign = 1 if text.startswith("-") else 0
    text = text.lstrip("-")
    if "e" in text:
        mantissa_text, exp_text = text.split("e")
        exponent = int(exp_text)
    else:
        mantissa_text, exponent = text, 0
    if "." in mantissa_text:
        whole, frac = mantissa_text.split(".")
        frac = frac.rstrip("0")
        mantissa = int(whole + frac) if whole + frac else 0
        exponent -= len(frac)
    else:
        mantissa = int(mantissa_text)
    biased = exponent + 0x1820
    out = bytearray(16)
    for i in range(14):
        out[i] = mantissa & 0xFF
        mantissa >>= 8
    out[14] = ((biased & 0x7F) << 1) | (mantissa & 1)
    out[15] = (sign << 7) | ((biased >> 7) & 0x7F)
    return bytes(out)


# --- cell records ---------------------------------------------------------------


class Cell:
    """One cell record: its type and its fields, keyed by flag."""

    def __init__(self, cell_type: int = _EMPTY, fields: Optional[Dict[int, bytes]] = None, extra: bytes = b"\0\0\0\0\0\0"):
        self.type = cell_type
        self.fields: Dict[int, bytes] = dict(fields or {})
        self.extra = extra  # bytes 2-7 of the header, kept as they were

    @classmethod
    def unpack(cls, buf: bytes) -> "Cell":
        cell_type = buf[1]
        flags = struct.unpack_from("<I", buf, 8)[0]
        offset = 12
        fields = {}
        for bit in range(32):
            flag = 1 << bit
            if flags & flag:
                size = _field_size(flag)
                fields[flag] = buf[offset : offset + size]
                offset += size
        return cls(cell_type, fields, buf[2:8])

    def pack(self) -> bytes:
        flags = 0
        body = b""
        for flag in sorted(self.fields):
            flags |= flag
            body += self.fields[flag]
        return bytes([5, self.type]) + self.extra + struct.pack("<I", flags) + body

    def int_field(self, flag: int) -> Optional[int]:
        raw = self.fields.get(flag)
        return None if raw is None else struct.unpack("<i", raw)[0]

    def set_int(self, flag: int, value: int) -> None:
        self.fields[flag] = struct.pack("<i", value)


def _tile_cells(row: Any) -> Dict[int, Cell]:
    """The cells in one tile row, by column."""
    buf = row.cell_storage_buffer
    offsets = struct.unpack(f"<{len(row.cell_offsets) // 2}H", row.cell_offsets)
    out = {}
    for column, offset in enumerate(offsets):
        if offset == 0xFFFF:
            continue
        if row.has_wide_offsets:
            offset *= 4
        out[column] = Cell.unpack(buf[offset:])
    return out


def _write_tile_row(row: Any, cells: Dict[int, Cell]) -> None:
    buf = b""
    offsets = [0xFFFF] * _TILE_SIZE
    pre_buf = b""
    pre_offsets = [0xFFFF] * _TILE_SIZE
    for column in sorted(cells):
        record = cells[column].pack()
        offsets[column] = len(buf)
        buf += record
        # Older readers see an empty version 4 cell in the same place.
        pre_offsets[column] = len(pre_buf)
        pre_buf += b"\x04" + b"\0" * 11
    row.cell_storage_buffer = buf
    row.cell_offsets = struct.pack(f"<{_TILE_SIZE}H", *offsets)
    row.cell_storage_buffer_pre_bnc = pre_buf
    row.cell_offsets_pre_bnc = struct.pack(f"<{_TILE_SIZE}H", *pre_offsets)
    row.cell_count = len(cells)
    row.storage_version = 5
    row.has_wide_offsets = False
    if len(buf) > 0xFFFE:
        raise ValueError("too much data in one table row")


# --- tables ---------------------------------------------------------------------


def _key_entries(data_list: Any) -> Dict[int, Any]:
    return {e.key: e for e in data_list.entries}


class Table(Drawable):
    """A table on a slide. Rows and columns count from 0, header rows included."""

    kind = "table"

    @property
    def _model(self) -> Any:
        return self._package.deref(self._archive.tableModel)

    @property
    def _store(self) -> Any:
        return self._model.base_data_store

    @property
    def name(self) -> str:
        return self._model.table_name

    @name.setter
    def name(self, value: str) -> None:
        self._model.table_name = value
        self._package.mark_changed(self._model_id)
        self.slide._touched()

    @property
    def _model_id(self) -> int:
        return self._archive.tableModel.identifier

    @property
    def row_count(self) -> int:
        return self._model.number_of_rows

    @property
    def column_count(self) -> int:
        return self._model.number_of_columns

    @property
    def header_rows(self) -> int:
        return self._model.number_of_header_rows

    @property
    def header_columns(self) -> int:
        return self._model.number_of_header_columns

    @property
    def footer_rows(self) -> int:
        return self._model.number_of_footer_rows

    def _tiles(self) -> List[Tuple[int, Any]]:
        p = self._package
        return [(t.tileid, p.deref(t.tile)) for t in self._store.tiles.tiles]

    def _cells(self) -> Dict[Tuple[int, int], Cell]:
        out = {}
        for tile_id, tile in self._tiles():
            for row in tile.rowInfos:
                for column, cell in _tile_cells(row).items():
                    out[(tile_id * _TILE_SIZE + row.tile_row_index, column)] = cell
        return out

    def _value(self, cell: Cell) -> Value:
        p = self._package
        if cell.type == _TEXT and _STRING in cell.fields:
            entries = _key_entries(p.deref(self._store.stringTable))
            entry = entries.get(cell.int_field(_STRING))
            return None if entry is None else entry.string
        if cell.type == _RICH and _RICH_ID in cell.fields:
            entry = _key_entries(p.deref(self._store.rich_text_table)).get(cell.int_field(_RICH_ID))
            if entry is not None and entry.HasField("rich_text_payload"):
                from .text import Text

                payload = p.deref(entry.rich_text_payload)
                return str(Text(p, payload.storage.identifier))
            return None
        if cell.type in (_NUMBER, 10):
            if _DECIMAL in cell.fields:
                value = unpack_decimal128(cell.fields[_DECIMAL])
            elif _DOUBLE in cell.fields:
                value = struct.unpack("<d", cell.fields[_DOUBLE])[0]
            else:
                return None
            return int(value) if value.is_integer() and abs(value) < 2**53 else value
        if cell.type == _BOOL and _DOUBLE in cell.fields:
            return bool(struct.unpack("<d", cell.fields[_DOUBLE])[0])
        if cell.type == _DATE and _SECONDS in cell.fields:
            return _EPOCH + datetime.timedelta(seconds=struct.unpack("<d", cell.fields[_SECONDS])[0])
        if cell.type == _DURATION and _DOUBLE in cell.fields:
            return struct.unpack("<d", cell.fields[_DOUBLE])[0]
        return None

    @property
    def rows(self) -> List[List[Value]]:
        """Every cell's value, row by row: text, a number, ``True``/``False``, a datetime, or ``None`` if empty."""
        grid: List[List[Value]] = [[None] * self.column_count for _ in range(self.row_count)]
        for (r, c), cell in self._cells().items():
            if r < self.row_count and c < self.column_count:
                grid[r][c] = self._value(cell)
        return grid

    def cell(self, row: int, column: int) -> Value:
        self._check(row, column)
        return self.rows[row][column]

    def _check(self, row: int, column: int) -> None:
        if not (0 <= row < self.row_count and 0 <= column < self.column_count):
            raise IndexError(f"cell ({row}, {column}) is outside the {self.row_count} x {self.column_count} table")

    def set_cell(self, row: int, column: int, value: Value) -> None:
        self._check(row, column)
        grid = self.rows
        grid[row][column] = value
        self._write(grid, keep=self._cells())

    def set_rows(self, rows: Sequence[Sequence[Value]]) -> None:
        """Replace every cell, resizing the table to fit. Row heights and column widths are kept where they exist."""
        grid = _grid(rows)
        self._resize(len(grid), len(grid[0]))
        self._write(grid, keep=self._cells())

    # --- writing ----------------------------------------------------------------

    def _format_key(self, format_type: int) -> int:
        p = self._package
        table = p.deref(self._store.format_table)
        for e in table.entries:
            if e.format.format_type == format_type:
                return e.key
        key = table.nextListID or 1
        table.nextListID = key + 1
        entry = table.entries.add(key=key, refcount=0)
        entry.format.format_type = format_type
        if format_type == _FORMAT_NUMBER:
            entry.format.decimal_places = 253
            entry.format.negative_style = 0
            entry.format.show_thousands_separator = False
        p.mark_changed(self._store.format_table.identifier)
        return key

    def _write(self, grid: List[List[Value]], keep: Dict[Tuple[int, int], Cell]) -> None:
        """Write every cell from ``grid``, keeping styles and formats of cells whose kind doesn't change."""
        p = self._package
        strings = p.deref(self._store.stringTable)
        text_key = self._format_key(_FORMAT_TEXT)
        number_key = self._format_key(_FORMAT_NUMBER)
        string_keys: Dict[str, int] = {}
        del strings.entries[:]
        next_key = 1

        rows: Dict[int, Dict[int, Cell]] = {}
        for r, row in enumerate(grid):
            for c, value in enumerate(row):
                old = keep.get((r, c))
                cell = Cell(extra=old.extra) if old is not None else Cell()
                if old is not None:
                    # Keep the cell's own style and anything else that isn't its value or format.
                    for flag, raw in old.fields.items():
                        if not flag & _VALUE_FLAGS and flag not in _FORMAT_FLAGS and flag != _SUGGEST:
                            cell.fields[flag] = raw
                if value is None or value == "":
                    if not cell.fields:
                        continue
                    cell.type = _EMPTY
                elif isinstance(value, bool):
                    cell.type = _BOOL
                    cell.fields[_DOUBLE] = struct.pack("<d", 1.0 if value else 0.0)
                elif isinstance(value, (int, float)):
                    cell.type = _NUMBER
                    cell.fields[_DECIMAL] = pack_decimal128(value)
                    cell.set_int(_SUGGEST, _SUGGEST_NUMBER)
                    cell.set_int(_NUM_FORMAT, number_key)
                elif isinstance(value, str):
                    if value not in string_keys:
                        string_keys[value] = next_key
                        strings.entries.add(key=next_key, refcount=0, string=value)
                        next_key += 1
                    cell.type = _TEXT
                    cell.set_int(_STRING, string_keys[value])
                    cell.set_int(_SUGGEST, _SUGGEST_TEXT)
                    cell.set_int(_TEXT_FORMAT, text_key)
                else:
                    raise TypeError(f"a cell can hold text, a number, True/False or None, not {type(value).__name__}")
                rows.setdefault(r, {})[c] = cell
        strings.nextListID = next_key
        p.mark_changed(self._store.stringTable.identifier)

        # Tiles: one per 256 rows.
        tiles = self._tiles()
        needed = (len(grid) + _TILE_SIZE - 1) // _TILE_SIZE
        if needed > len(tiles):
            raise ValueError(f"tables of more than {len(tiles) * _TILE_SIZE} rows aren't supported")
        for tile_id, tile in tiles:
            del tile.rowInfos[:]
            first = tile_id * _TILE_SIZE
            count = 0
            for r in range(first, min(first + _TILE_SIZE, len(grid))):
                info = tile.rowInfos.add()
                info.tile_row_index = r - first
                _write_tile_row(info, rows.get(r, {}))
                count += 1
            tile.numrows = count
            tile.maxColumn = tile.maxRow = tile.numCells = 0
            tile.storage_version = 5
            tile.last_saved_in_BNC = True
        for t in self._store.tiles.tiles:
            p.mark_changed(t.tile.identifier)

        # Reference counts and per-row/column cell counts.
        counts = {}
        for row in rows.values():
            for cell in row.values():
                for flag in _FORMAT_FLAGS:
                    key = cell.int_field(flag)
                    if key is not None:
                        counts[key] = counts.get(key, 0) + 1
                key = cell.int_field(_STRING)
                if key is not None:
                    entry = _key_entries(strings)[key]
                    entry.refcount += 1
        formats = p.deref(self._store.format_table)
        for e in formats.entries:
            e.refcount = counts.get(e.key, 0)
        kept = [e for e in formats.entries if e.refcount > 0]
        del formats.entries[:]
        for e in kept:
            formats.entries.add().CopyFrom(e)
        p.mark_changed(self._store.format_table.identifier)

        for header in self._row_headers():
            header.numberOfCells = len(rows.get(header.index, {}))
        for header in self._column_headers():
            header.numberOfCells = sum(1 for row in rows.values() if header.index in row)
        self._headers_changed()
        self.slide._touched()
        p.mark_changed(self._model_id)

    # --- size -------------------------------------------------------------------

    def _row_bucket(self) -> Any:
        return self._package.deref(self._store.rowHeaders.buckets[0])

    def _column_bucket(self) -> Any:
        return self._package.deref(self._store.columnHeaders)

    def _row_headers(self) -> List[Any]:
        return list(self._row_bucket().headers)

    def _column_headers(self) -> List[Any]:
        return list(self._column_bucket().headers)

    def _headers_changed(self) -> None:
        p = self._package
        p.mark_changed(self._store.rowHeaders.buckets[0].identifier)
        p.mark_changed(self._store.columnHeaders.identifier)

    @property
    def row_heights(self) -> List[float]:
        sizes = {h.index: h.size for h in self._row_headers()}
        default = self._model.default_row_height
        return [sizes.get(i) or default for i in range(self.row_count)]

    @property
    def column_widths(self) -> List[float]:
        sizes = {h.index: h.size for h in self._column_headers()}
        default = self._model.default_column_width
        return [sizes.get(i) or default for i in range(self.column_count)]

    def set_row_heights(self, heights: Sequence[float]) -> None:
        self._set_sizes(self._row_bucket(), self.row_count, heights)

    def set_column_widths(self, widths: Sequence[float]) -> None:
        self._set_sizes(self._column_bucket(), self.column_count, widths)

    def _set_sizes(self, bucket: Any, count: int, sizes: Sequence[float]) -> None:
        if len(sizes) != count:
            raise ValueError(f"need {count} sizes, not {len(sizes)}")
        existing = {h.index: h for h in bucket.headers}
        for i, size in enumerate(sizes):
            h = existing.get(i)
            if h is None:
                h = bucket.headers.add(index=i, hidingState=0, numberOfCells=0)
            h.size = float(size)
        self._fit_frame()
        self._headers_changed()

    def _fit_frame(self) -> None:
        g = self._info.geometry
        g.size.width = sum(self.column_widths)
        g.size.height = sum(self.row_heights)
        self._package.mark_changed(self.identifier)
        self.slide._touched()

    def _resized(self) -> None:
        # Spread the new frame over the rows and columns in proportion.
        width, height = self._info.geometry.size.width, self._info.geometry.size.height
        widths, heights = self.column_widths, self.row_heights
        self.set_column_widths([w * width / sum(widths) for w in widths])
        self.set_row_heights([h * height / sum(heights) for h in heights])

    def _resize(self, rows: int, columns: int) -> None:
        if rows < 1 or columns < 1:
            raise ValueError("a table needs at least one row and one column")
        if columns > _TILE_SIZE:
            raise ValueError(f"tables of more than {_TILE_SIZE} columns aren't supported")
        m = self._model
        for bucket, count, default in (
            (self._row_bucket(), rows, self.row_heights[-1]),
            (self._column_bucket(), columns, self.column_widths[-1]),
        ):
            existing = {h.index: h for h in bucket.headers}
            del bucket.headers[:]
            for i in range(count):
                h = bucket.headers.add()
                if i in existing:
                    h.CopyFrom(existing[i])
                else:
                    h.index, h.size, h.hidingState, h.numberOfCells = i, default, 0, 0
        m.number_of_rows = rows
        m.number_of_columns = columns
        m.number_of_header_rows = min(m.number_of_header_rows, rows)
        m.number_of_header_columns = min(m.number_of_header_columns, columns)
        m.number_of_footer_rows = min(m.number_of_footer_rows, rows - m.number_of_header_rows)
        _set_uids(self._package.deref(m.base_column_row_uids), rows, columns)
        self._package.mark_changed(m.base_column_row_uids.identifier)
        self._package.mark_changed(self._model_id)
        self._fit_frame()
        self._headers_changed()

    def set_headers(self, rows: Optional[int] = None, columns: Optional[int] = None, footer_rows: Optional[int] = None) -> None:
        """Set how many header rows, header columns and footer rows the table has."""
        m = self._model
        if rows is not None:
            if not 0 <= rows <= min(5, self.row_count):
                raise ValueError("header rows must be 0 to 5, and no more than the table has")
            m.number_of_header_rows = rows
        if columns is not None:
            if not 0 <= columns <= min(5, self.column_count):
                raise ValueError("header columns must be 0 to 5, and no more than the table has")
            m.number_of_header_columns = columns
        if footer_rows is not None:
            if not 0 <= footer_rows <= min(5, self.row_count - m.number_of_header_rows):
                raise ValueError("footer rows must be 0 to 5, and fit below the header rows")
            m.number_of_footer_rows = footer_rows
        self._package.mark_changed(self._model_id)
        self.slide._touched()

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update(name=self.name, header_rows=self.header_rows, header_columns=self.header_columns, rows=self.rows)
        return d

    def _owned_elsewhere(self) -> List[int]:
        return []


def _grid(rows: Sequence[Sequence[Value]]) -> List[List[Value]]:
    rows = [list(r) for r in rows]
    if not rows or not any(rows):
        raise ValueError("a table needs at least one row and one column")
    width = max(len(r) for r in rows)
    return [r + [None] * (width - len(r)) for r in rows]


def _set_uids(uid_map: Any, rows: int, columns: int) -> None:
    """Give every row and column a UUID, as ``TST.ColumnRowUIDMapArchive`` lists them."""
    for kind, count in (("column", columns), ("row", rows)):
        uids = [new_uuid_parts() for _ in range(count)]
        order = sorted(range(count), key=lambda i: (uids[i][1], uids[i][0]))
        sorted_field = getattr(uid_map, f"sorted_{kind}_uids")
        del sorted_field[:]
        for i in order:
            u = sorted_field.add()
            u.lower, u.upper = uids[i]
        index_for_uid = getattr(uid_map, f"{kind}_index_for_uid")
        uid_for_index = getattr(uid_map, f"{kind}_uid_for_index")
        del index_for_uid[:]
        del uid_for_index[:]
        index_for_uid.extend(order)  # the index of each sorted UUID
        position = {index: pos for pos, index in enumerate(order)}
        uid_for_index.extend(position[i] for i in range(count))  # where each index's UUID sits in the sorted list
