from pathlib import Path

import pytest

from pykeynote import Presentation, from_markdown, parse_markdown
from pykeynote.drawables import SHAPE_KINDS, parse_color
from pykeynote.package import references_in
from pykeynote.tables import pack_decimal128, unpack_decimal128

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE = FIXTURES / "shapes-tables-charts.key"


@pytest.fixture
def deck():
    return Presentation.open(FIXTURE)


def reopen(deck, tmp_path, name="out.key"):
    path = tmp_path / name
    deck.save(path)
    return Presentation.open(path)


def assert_no_dangling_references(deck):
    p = deck.package
    missing = [(i, r) for i, obj in p.objects() for r in references_in(obj) if r not in p]
    assert missing == []


# --- reading what Keynote wrote ---------------------------------------------------


def test_reads_keynote_shapes(deck):
    shape, box = deck[0].shapes
    assert shape.kind == "rectangle"
    assert shape.position == (200, 200)
    assert shape.size == (600, 400)
    assert shape.text == "Hello shape"
    assert shape.fill == "#000000"
    assert box.kind == "text box"
    assert box.text == "Free text"


def test_reads_keynote_table(deck):
    (table,) = deck[1].tables
    assert (table.row_count, table.column_count, table.header_rows) == (4, 3, 1)
    assert table.rows == [["Name", "Score", "Note"], ["Ada", 42, "first"], ["Bob", 3.5, "second"], ["Cy", -7, None]]
    assert table.cell(2, 1) == 3.5


def test_reads_keynote_charts(deck):
    types = [s.charts[0].chart_type for s in deck.slides[2:]]
    assert types == ["column", "line", "pie"]
    chart = deck[2].charts[0]
    assert chart.row_names == ["2024", "2025"]
    assert chart.column_names == ["Q1", "Q2", "Q3"]
    assert chart.data == [[1, 2, 3], [4, 5, 6]]
    assert chart.series_by == "row"
    assert chart.series == ["2024", "2025"]


def test_slide_lists_drawables_by_kind(deck):
    assert [d.kind for d in deck[0].drawables] == ["rectangle", "text box"]
    assert deck[1].tables and not deck[1].charts and not deck[1].shapes


# --- shapes -----------------------------------------------------------------------


def test_add_every_shape_kind(tmp_path):
    deck = Presentation.new()
    slide = deck.add_slide("Blank")
    for i, kind in enumerate(SHAPE_KINDS):
        slide.add_shape(kind, x=10 + i, y=20, width=200, height=100, text=kind, style=i % 6)
    slide.add_text_box("Free text", x=10, y=900, width=500, height=60)
    out = reopen(deck, tmp_path)
    shapes = out[0].shapes
    assert [s.kind for s in shapes] == list(SHAPE_KINDS) + ["text box"]
    assert [s.text for s in shapes] == list(SHAPE_KINDS) + ["Free text"]
    assert shapes[3].position == (13, 20)
    assert shapes[3].size == (200, 100)
    assert_no_dangling_references(out)


def test_shape_fill_and_resize(tmp_path):
    deck = Presentation.new()
    slide = deck.add_slide("Blank")
    shape = slide.add_shape("oval", fill="#3366ff")
    assert shape.fill == "#3366ff"
    shape.size = (300, 150)
    shape.position = (5, 6)
    shape.fill = "orange"
    out = reopen(deck, tmp_path)
    (shape,) = out[0].shapes
    assert shape.fill == "#ff9400"
    assert shape.size == (300, 150)
    assert shape.position == (5, 6)
    assert shape.kind == "oval"


def test_shape_fill_on_keynote_shape(deck, tmp_path):
    deck[0].shapes[0].fill = (1, 0, 0)
    assert reopen(deck, tmp_path)[0].shapes[0].fill == "#ff0000"


def test_bad_shape_arguments():
    slide = Presentation.new().add_slide("Blank")
    with pytest.raises(ValueError):
        slide.add_shape("blob")
    with pytest.raises(ValueError):
        slide.add_shape(width=0)
    with pytest.raises(ValueError):
        slide.add_shape(style=6)


def test_parse_color():
    assert parse_color("#fff") == (1, 1, 1, 1)
    assert parse_color("#00000080")[3] == pytest.approx(0.5, abs=0.01)
    assert parse_color((0.5, 0.5, 0.5)) == (0.5, 0.5, 0.5, 1)
    with pytest.raises(ValueError):
        parse_color("nope")


def test_build_on_a_shape(tmp_path):
    deck = Presentation.new()
    slide = deck.add_slide("Blank")
    shape = slide.add_shape("star")
    slide.add_build(shape)
    out = reopen(deck, tmp_path)
    assert out[0].builds[0].target == out[0].shapes[0].identifier


# --- charts -----------------------------------------------------------------------


def test_add_chart(tmp_path):
    deck = Presentation.new()
    slide = deck.add_slide("Blank")
    slide.add_chart("line", [[1, 2], [3, None]], ["A", "B"], ["x", "y"], x=10, y=20, width=500, height=400, style=3)
    slide.add_chart("pie", [[3, 5, 2]], ["Share"], ["a", "b", "c"], width=600, height=400)
    out = reopen(deck, tmp_path)
    line, pie = out[0].charts
    assert line.chart_type == "line"
    assert line.data == [[1, 2], [3, None]]
    assert line.position == (10, 20)
    assert line.show_legend
    assert pie.chart_type == "pie"
    assert pie.series_by == "column"  # so the first row's values are the slices
    assert pie.size == (400, 400)
    assert_no_dangling_references(out)


def test_chart_set_data_and_type(deck, tmp_path):
    chart = deck[2].charts[0]
    chart.set_data([[9, 8]], ["Only"], ["P", "Q"])
    chart.chart_type = "bar"
    out = reopen(deck, tmp_path)
    chart = out[2].charts[0]
    assert (chart.chart_type, chart.row_names, chart.data) == ("bar", ["Only"], [[9, 8]])


def test_chart_data_must_match_names():
    slide = Presentation.new().add_slide("Blank")
    with pytest.raises(ValueError):
        slide.add_chart("column", [[1, 2]], ["A"], ["x"])
    with pytest.raises(ValueError):
        slide.add_chart("radial", [[1]], ["A"], ["x"])


# --- tables -----------------------------------------------------------------------


def test_add_table(tmp_path):
    deck = Presentation.new()
    slide = deck.add_slide("Title Only", title="Scores")
    rows = [["Name", "Score", "Note"], ["Ada", 42, "first"], ["Bob", 3.5, None], ["Cy", -7, True]]
    table = slide.add_table(rows, header_columns=1, style=2)
    out = reopen(deck, tmp_path)
    (table,) = out[0].tables
    assert table.rows == rows
    assert (table.header_rows, table.header_columns) == (1, 1)
    assert table.size == (900, 256)
    assert table.name == "Table 1"
    assert_no_dangling_references(out)


def test_table_cells_match_keynote(deck):
    """Cells written by pykeynote are byte for byte what Keynote wrote for the same values."""
    keynote = deck[1].tables[0]
    ours = Presentation.new().add_slide("Blank").add_table(keynote.rows)
    for (_, a), (_, b) in zip(keynote._tiles(), ours._tiles()):
        assert [r.cell_storage_buffer for r in a.rowInfos] == [r.cell_storage_buffer for r in b.rowInfos]
        assert [r.cell_offsets for r in a.rowInfos] == [r.cell_offsets for r in b.rowInfos]


def test_edit_keynote_table(deck, tmp_path):
    table = deck[1].tables[0]
    table.set_cell(3, 2, "third")
    table.set_cell(1, 1, 43)
    out = reopen(deck, tmp_path)
    assert out[1].tables[0].rows[1:] == [["Ada", 43, "first"], ["Bob", 3.5, "second"], ["Cy", -7, "third"]]


def test_resize_table(deck, tmp_path):
    table = deck[1].tables[0]
    table.set_rows([["a", "b", "c", "d"], [1, 2, 3, 4]] + [[i] for i in range(5)])
    out = reopen(deck, tmp_path)
    table = out[1].tables[0]
    assert (table.row_count, table.column_count) == (7, 4)
    assert table.rows[2] == [0, None, None, None]
    assert len(table.row_heights) == 7


def test_two_tables_get_their_own_formula_owners(tmp_path):
    deck = Presentation.new()
    slide = deck.add_slide("Blank")
    a = slide.add_table([["a"], [1]])
    b = slide.add_table([["b"], [2]])
    assert a._model.table_id != b._model.table_id
    engine = deck.package.get(deck.package.component_for_file("Index/CalculationEngine.iwa").identifier)
    internal = [e.internal_owner_id for e in engine.dependency_tracker.owner_id_map.map_entry]
    assert len(internal) == len(set(internal))
    owners = [e.owner_id.uuid_w0 for e in engine.dependency_tracker.owner_id_map.map_entry]
    assert len(owners) == len(set(owners))
    assert [t.name for t in reopen(deck, tmp_path)[0].tables] == ["Table 1", "Table 2"]


def test_decimal128_round_trip():
    for value in (0, 1, -7, 42, 3.5, 0.1, 1e6, 123456.789, -0.0025):
        assert unpack_decimal128(pack_decimal128(value)) == pytest.approx(value)


# --- removing and copying -------------------------------------------------------------


def test_delete_drawables_leaves_nothing_behind(tmp_path):
    deck = Presentation.new()
    slide = deck.add_slide("Blank")
    before = len(list(deck.package.objects()))
    slide.add_table([["a", "b"], [1, 2]])
    slide.add_chart("column", [[1, 2]], ["x"], ["a", "b"])
    slide.add_shape("oval", text="hi")
    for d in slide.drawables:
        slide.delete_drawable(d)
    assert slide.drawables == []
    # Only the (now empty) object container Keynote keeps chart settings in is left.
    assert len(list(deck.package.objects())) == before + 1
    out = reopen(deck, tmp_path)
    assert out[0].drawables == []
    assert_no_dangling_references(out)


def test_duplicate_slide_copies_tables_and_charts(deck, tmp_path):
    copy = deck.duplicate_slide(1)
    copy.tables[0].set_cell(1, 0, "Changed")
    chart_copy = deck.duplicate_slide(3)
    chart_copy.charts[0].set_data([[1]], ["r"], ["c"])
    out = reopen(deck, tmp_path)
    assert out[1].tables[0].cell(1, 0) == "Ada"
    assert out[2].tables[0].cell(1, 0) == "Changed"
    assert out[1].tables[0].identifier != out[2].tables[0].identifier
    assert out[3].charts[0].data == [[1, 2, 3], [4, 5, 6]]
    assert out[4].charts[0].data == [[1]]
    assert_no_dangling_references(out)


def test_delete_slide_with_a_table(deck, tmp_path):
    deck.delete_slide(1)
    out = reopen(deck, tmp_path)
    assert all(not s.tables for s in out)
    assert not [n for n in out.package.filenames if n.startswith("Index/Tables/")]
    assert_no_dangling_references(out)


# --- Markdown ---------------------------------------------------------------------------

MARKDOWN = """# Scores

| Name | Score | Note |
| --- | --- | --- |
| Ada | 42 | first |
| Bob | 3.5 | a \\| pipe |
| Cy | -7 |  |
"""


def test_markdown_table_round_trip(tmp_path):
    deck = from_markdown(MARKDOWN)
    (table,) = deck[0].tables
    assert table.header_rows == 1
    assert table.rows == [["Name", "Score", "Note"], ["Ada", 42, "first"], ["Bob", 3.5, "a | pipe"], ["Cy", -7, None]]
    assert deck[0].layout == "Title Only"
    md = reopen(deck, tmp_path).to_markdown()
    assert md.endswith(MARKDOWN.split("\n", 2)[2])
    assert parse_markdown(md)[0].tables == parse_markdown(MARKDOWN)[0].tables


def test_markdown_table_without_header():
    (spec,) = parse_markdown("|  |  |\n| --- | --- |\n| a | TRUE |\n")
    assert spec.tables[0].rows == [["a", True]]
    assert spec.tables[0].header_rows == 0
    assert spec.default_layout() == "Blank"


def test_keynote_table_exports_to_markdown(deck):
    assert "| Name | Score | Note |\n| --- | --- | --- |\n| Ada | 42 | first |" in deck.to_markdown()


def test_new_table_id_is_its_calc_engine_uuid():
    """Keynote drops a table whose table_id isn't the UUID of its base formula owner."""
    import uuid

    from pykeynote.tables import _table_uid

    for deck, table in [
        (lambda d: (d, d[1].tables[0]))(Presentation.open(FIXTURE)),
        (lambda d: (d, d.add_slide("Blank").add_table([["a"], [1]])))(Presentation.new()),
    ]:
        u = _table_uid(deck.package, table)
        value = (u.upper << 64) | u.lower
        assert table._model.table_id == str(uuid.UUID(bytes=value.to_bytes(16, "little"))).upper()
