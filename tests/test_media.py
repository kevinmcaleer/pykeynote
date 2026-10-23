import hashlib
import struct
import zlib
from pathlib import Path

import pytest

from pykeynote import Presentation, from_markdown, parse_markdown
from pykeynote.media import image_format

from test_slides import check_consistent, reopen

FIXTURES = Path(__file__).parent / "fixtures"


def png(width, height, rgb=(200, 30, 30)):
    """A solid-colour PNG, made without any imaging library."""
    row = b"\x00" + bytes(rgb) * width
    raw = zlib.compress(row * height)

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", raw)
        + chunk(b"IEND", b"")
    )


def jpeg_header(width, height):
    """Just enough of a JPEG for its size to be read."""
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00"
    return b"\xff\xd8" + app0 + sof + b"\xff\xd9"


def test_image_format():
    assert image_format(png(30, 20)) == ("png", 30, 20)
    assert image_format(jpeg_header(640, 480)) == ("jpeg", 640, 480)
    assert image_format(b"GIF89a" + struct.pack("<HH", 7, 9) + b"\x00" * 8) == ("gif", 7, 9)
    with pytest.raises(ValueError, match="PNG, JPEG and GIF"):
        image_format(b"not an image at all")


def test_read_placeholder_sample():
    deck = Presentation.open(FIXTURES / "layouts-basic-white.key")
    photo = next(s for s in deck if s.layout == "Photo")
    (image,) = photo.images
    assert image.placeholder == "Media"
    assert image.is_sample and image.filename is None
    assert image.position == (0, 0) and image.size == (1024, 768)
    assert image.description


def test_new_picture_drops_the_sample_description():
    """Keynote shows the sample photo's caption as the new picture's description otherwise."""
    slide = Presentation.new().add_slide("Title & Photo", title="Robots")
    assert slide.placeholders[0].description
    image = slide.add_image(png(20, 10))
    assert image.description == ""
    assert slide.replace_image(image, png(10, 10)).description == ""


def test_fill_placeholder(tmp_path):
    deck = Presentation.new()
    slide = deck.add_slide("Title & Photo", title="Robots")
    before = slide.placeholders[0]
    added = slide.add_image(png(1600, 900), description="A red square")
    assert added.identifier == before.identifier
    assert (added.position, added.size) == (before.position, before.size)

    again = reopen(deck, tmp_path)
    (image,) = again[0].images
    assert image.placeholder == "Media" and not image.is_sample
    assert image.pixel_size == (1600, 900)
    assert image.description == "A red square"
    assert image.data == png(1600, 900)
    assert image.position == before.position and image.size == before.size
    # The picture itself covers the crop, keeping its shape.
    obj = again.package.get(image.identifier)
    g = obj.super.geometry
    assert g.size.width / g.size.height == pytest.approx(16 / 9)
    assert g.size.width >= image.size[0] - 0.01 and g.size.height >= image.size[1] - 0.01
    assert not obj.HasField("thumbnailData")
    check_consistent(again)
    check_data(again)


def check_data(deck):
    """Every data file an image uses is in the package with the right digest and listed in its component."""
    p = deck.package
    infos = {i.identifier: i for i in p.metadata.datas}
    for slide in deck:
        component = p.component_for_file(p.file_of(slide._slide_id))
        used = {(o.object_identifier, r.data_identifier) for r in component.data_references for o in r.object_reference_list}
        for image in slide.images:
            obj = p.get(image.identifier)
            assert obj.data.identifier in p.segment(image.identifier).header.message_infos[0].data_references
            assert (image.identifier, obj.data.identifier) in used
            if not image.is_sample:
                info = infos[obj.data.identifier]
                data = p.read_file("Data/" + info.file_name)
                assert hashlib.sha1(data).digest() == info.digest
                assert info.materialized_length == len(data)
    files = {"Data/" + i.file_name for i in infos.values() if i.file_name}
    assert {n for n in p.filenames if n.startswith("Data/")} <= files


def test_add_free_image(tmp_path):
    deck = Presentation.new()
    slide = deck.add_slide("Blank")
    centred = slide.add_image(png(400, 300))
    placed = slide.add_image(png(800, 800, (0, 0, 200)), position=(100, 50), size=(200, None), description="Blue")
    assert centred.position == (760, 390) and centred.size == (400, 300)
    assert placed.size == (200, 200)

    big = slide.add_image(png(4000, 1000), placeholder=False)
    assert big.size == pytest.approx((1536, 384))  # fits in 80% of the slide

    again = reopen(deck, tmp_path)
    images = again[0].images
    assert [i.size for i in images] == [(400, 300), (200, 200), pytest.approx((1536, 384))]
    assert images[1].position == (100, 50) and images[1].description == "Blue"
    assert all(i.placeholder is None for i in images)
    check_consistent(again)
    check_data(again)


def test_same_picture_stored_once(tmp_path):
    deck = Presentation.new()
    slide = deck.add_slide("Blank")
    slide.add_image(png(10, 10), name="a.png")
    slide.add_image(png(10, 10), name="b.png")
    again = reopen(deck, tmp_path)
    a, b = again[0].images
    assert a.filename == b.filename == f"a-{again.package.get(a.identifier).data.identifier}.png"


def test_add_image_from_path(tmp_path):
    path = tmp_path / "my photo.png"
    path.write_bytes(png(50, 40))
    deck = Presentation.new()
    image = deck.add_slide("Blank").add_image(path)
    assert image.filename.startswith("my-photo-") and image.filename.endswith(".png")
    with pytest.raises(ValueError, match="download"):
        deck[0].add_image("https://example.com/robot.png")


def test_replace_and_remove(tmp_path):
    deck = Presentation.new()
    slide = deck.add_slide("Photo - 3 Up")
    assert [i.placeholder for i in slide.placeholders] == ["Media", "Media-1", "Media-2"]
    slide.add_image(png(100, 100))
    slide.add_image(png(100, 100, (0, 200, 0)), placeholder="Media-2")
    assert [i.is_sample for i in slide.placeholders] == [False, True, False]
    slide.remove_image("Media-1")
    free = slide.add_image(png(300, 100), position=(0, 0), size=(300, 100))
    slide.add_build(free.identifier, "dissolve")

    again = reopen(deck, tmp_path)
    slide = again[0]
    assert [i.placeholder for i in slide.images] == ["Media-2", "Media", None]  # back to front
    slide.replace_image(-1, png(100, 100, (9, 9, 9)))
    replaced = slide.images[-1]
    assert replaced.size == (100, 100) and replaced.position == (100, 0)  # fits in the old frame
    old_file = slide.images[1].filename
    slide.remove_image("Media")
    slide.remove_image(replaced)
    assert slide.builds == []

    final = reopen(again, tmp_path, "final.key")
    assert [i.placeholder for i in final[0].images] == ["Media-2"]
    assert "Data/" + old_file not in final.package.filenames
    assert "Media" not in [e.tag for e in final[0]._slide.sage_tag_to_info_map]
    check_consistent(final)
    check_data(final)


def test_image_errors():
    deck = Presentation.new()
    slide = deck.add_slide("Blank")
    with pytest.raises(ValueError, match="no empty media placeholder"):
        slide.add_image(png(10, 10), placeholder=True)
    with pytest.raises(ValueError, match="no image"):
        slide.remove_image(0)
    with pytest.raises(ValueError, match="no media placeholder"):
        slide.replace_image("Media", png(10, 10))


def test_image_on_opened_deck(tmp_path):
    deck = Presentation.open(FIXTURES / "builds-talk.key")
    deck[1].add_image(png(64, 64), position=(10, 10))
    again = reopen(deck, tmp_path)
    assert again[1].images[-1].size == (64, 64)
    check_consistent(again)
    check_data(again)


MARKDOWN = """# Robots

![A red robot](red.png)

---

# Parts

- Motors
- Sensors

![Wiring](parts/wiring.png)
![Logo](red.png "1700,40 160x90")

---

![One](red.png)
![Two](parts/wiring.png)
"""


def test_markdown_images(tmp_path):
    (tmp_path / "parts").mkdir()
    (tmp_path / "red.png").write_bytes(png(160, 90))
    (tmp_path / "parts" / "wiring.png").write_bytes(png(90, 160, (0, 0, 255)))
    specs = parse_markdown(MARKDOWN)
    assert [i.path for i in specs[1].images] == ["parts/wiring.png", "red.png"]
    assert (specs[1].images[1].position, specs[1].images[1].size) == ((1700, 40), (160, 90))

    deck = from_markdown(MARKDOWN, base_dir=str(tmp_path))
    assert [s.layout for s in deck] == ["Title & Photo", "Title, Bullets & Photo", "Photo - 3 Up"]
    # The unused third placeholder is removed rather than showing a sample photo.
    assert [len(s.images) for s in deck] == [1, 2, 2]
    assert not any(i.is_sample for s in deck for i in s.images)

    again = reopen(deck, tmp_path)
    md = again.to_markdown(image_dir=str(tmp_path / "out"))
    first = again[0].images[0]
    assert first.name == "red.png"
    assert f"![A red robot]({tmp_path / 'out' / 'red.png'})".replace("\\", "/") in md
    assert (tmp_path / "out" / "red.png").read_bytes() == png(160, 90)
    assert '"1700,40 160x90")' in md
    rebuilt = from_markdown(md)
    assert rebuilt.to_markdown(image_dir=str(tmp_path / "out")) == md
    check_consistent(again)


def test_markdown_without_image_dir_and_escaping():
    deck = Presentation.new()
    slide = deck.add_slide("Title & Photo", title="T")
    slide.add_image(png(10, 10), description="a [b] c", name="pic.png")
    md = deck.to_markdown()
    assert "![a [b\\] c](pic.png)" in md
    assert parse_markdown(md)[0].images[0].description == "a [b] c"
    statement = Presentation.new()
    statement.add_slide("Statement", body="![not an image](x.png)")
    assert parse_markdown(statement.to_markdown())[0].images == []


def test_markdown_images_in_every_theme(tmp_path):
    from pykeynote import themes

    (tmp_path / "parts").mkdir()
    (tmp_path / "red.png").write_bytes(png(160, 90))
    (tmp_path / "parts" / "wiring.png").write_bytes(png(90, 160, (0, 0, 255)))
    for theme in themes():
        deck = from_markdown(MARKDOWN, theme=theme, base_dir=str(tmp_path))
        assert [len(s.images) for s in deck] == [1, 2, 2], theme
        assert not any(i.is_sample for s in deck for i in s.images)
        check_consistent(reopen(deck, tmp_path))
