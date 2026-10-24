import struct
from pathlib import Path

import pytest

from pykeynote import Presentation, from_markdown, parse_markdown
from pykeynote.movies import media_info

from test_media import png
from test_slides import check_consistent, reopen

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE = FIXTURES / "media-video-audio.key"


@pytest.fixture(scope="module")
def keynote_media():
    """The video and sound Keynote stored in the fixture deck."""
    p = Presentation.open(FIXTURE).package
    return p.read_file("Data/clip-9072.mp4"), p.read_file("Data/tone-9074.m4a")


def test_read_keynote_movies():
    deck = Presentation.open(FIXTURE)
    (video,) = deck[0].movies
    assert (video.position, video.size, video.pixel_size) == ((200, 200), (640, 360), (640, 360))
    assert video.duration == 2.5 and not video.audio_only
    assert (video.volume, video.loop, video.placeholder) == (1.0, "none", None)
    assert video.name == "clip.mp4" and video.data[4:8] == b"ftyp"
    (sound,) = deck[1].movies
    assert sound.audio_only and sound.size == (0, 0) and sound.name == "tone.m4a"
    assert sound.duration == pytest.approx(2.475, abs=0.001)
    (filled,) = deck[2].movies
    assert filled.placeholder == "Media" and filled.size == (1920, 1080)
    assert deck[2].images == [] and deck[0].images == []


def test_media_info(keynote_media):
    clip, tone = keynote_media
    assert media_info(clip) == ("mp4", 2.5, (640, 360))
    assert media_info(tone) == ("m4a", 2.5, None)
    with pytest.raises(ValueError, match="MPEG-4"):
        media_info(png(10, 10))
    # A 64-bit box size and a QuickTime brand.
    mvhd = b"\x01" + b"\x00" * 3 + b"\x00" * 16 + struct.pack(">IQ", 600, 1200) + b"\x00" * 80
    mvhd = struct.pack(">I4s", 8 + len(mvhd), b"mvhd") + mvhd
    tkhd = b"\x00" * 76 + struct.pack(">II", 320 << 16, 240 << 16)
    tkhd = struct.pack(">I4s", 8 + len(tkhd), b"tkhd") + tkhd
    hdlr = b"\x00" * 8 + b"vide" + b"\x00" * 12
    hdlr = struct.pack(">I4s", 8 + len(hdlr), b"hdlr") + hdlr
    # QuickTime puts a second, data handler box in minf, after the media handler.
    dhlr = b"\x00" * 8 + b"alis" + b"\x00" * 12
    minf = struct.pack(">I4s", 8 + 8 + len(dhlr), b"minf") + struct.pack(">I4s", 8 + len(dhlr), b"hdlr") + dhlr
    mdia = struct.pack(">I4s", 8 + len(hdlr) + len(minf), b"mdia") + hdlr + minf
    trak = struct.pack(">I4s", 8 + len(tkhd) + len(mdia), b"trak") + tkhd + mdia
    body = mvhd + trak
    moov = struct.pack(">I4sQ", 1, b"moov", 16 + len(body)) + body
    ftyp = struct.pack(">I4s", 16, b"ftyp") + b"qt  " + b"\x00" * 4
    assert media_info(ftyp + moov) == ("mov", 2.0, (320, 240))


def test_add_movie_and_sound(tmp_path, keynote_media):
    clip, tone = keynote_media
    deck = Presentation.new()
    slide = deck.add_slide("Blank")
    video = slide.add_movie(clip, position=(200, 200), size=(640, None), description="A test pattern", loop="repeat", volume=0.5)
    sound = deck.add_slide("Blank").add_audio(tone, name="tone.m4a")
    slide.add_build(video, "dissolve")

    again = reopen(deck, tmp_path)
    check_consistent(again)
    (v,) = again[0].movies
    assert (v.position, v.size, v.pixel_size, v.duration) == ((200, 200), (640, 360), (640, 360), 2.5)
    assert (v.description, v.loop, v.volume, v.audio_only) == ("A test pattern", "repeat", 0.5, False)
    assert v.data == clip
    assert again[0].builds[0].target == v.identifier
    (s,) = again[1].movies
    assert s.audio_only and s.position == (960, 540) and s.size == (0, 0)
    assert s.name == "tone.m4a" and s.data == tone
    obj = again.package.get(v.identifier)
    poster = again.package.read_file(f"Data/{[i for i in again.package.metadata.datas if i.identifier == obj.posterImageData.identifier][0].file_name}")
    assert poster[:4] == b"\x89PNG"
    assert sound.identifier == s.identifier


def test_movie_fills_placeholder(tmp_path, keynote_media):
    clip, _ = keynote_media
    deck = Presentation.new()
    slide = deck.add_slide("Title & Photo", title="Video")
    before = slide.placeholders[0]
    movie = slide.add_movie(clip, poster=png(640, 360))
    assert movie.identifier == before.identifier and movie.placeholder == "Media"
    assert slide.images == [] and slide.placeholders == []

    again = reopen(deck, tmp_path)
    check_consistent(again)
    (m,) = again[0].movies
    assert (m.position, m.size, m.placeholder) == ((0, 0), (1920, 1080), "Media")
    obj = again.package.get(m.identifier)
    assert not any(r for r in again.package.segment(m.identifier).header.message_infos[0].object_references if r not in again.package)
    assert obj.flags == 3


def test_sound_rejects_video_and_placeholders(keynote_media):
    clip, tone = keynote_media
    slide = Presentation.new().add_slide("Title & Photo")
    with pytest.raises(ValueError, match="picture"):
        slide.add_audio(clip)
    assert slide.movies == []
    with pytest.raises(ValueError, match="placeholder"):
        slide.add_movie(tone, placeholder=True)
    with pytest.raises(ValueError, match="loop"):
        slide.add_movie(clip, loop="forever")


def test_remove_movie(tmp_path, keynote_media):
    clip, tone = keynote_media
    deck = Presentation.new()
    one = deck.add_slide("Blank")
    two = deck.add_slide("Title & Photo")
    first = one.add_movie(clip, position=(0, 0))
    two.add_movie(clip)  # the same file, stored once
    one.add_audio(tone)
    one.add_build(first, "dissolve")
    one.remove_movie(first)
    assert [m.audio_only for m in one.movies] == [True] and one.builds == []
    one.remove_movie(0)
    two.remove_movie("Media")
    assert two.movies == [] and not any(i.placeholder for i in two.images)

    again = reopen(deck, tmp_path)
    check_consistent(again)
    names = [n for n in again.package.filenames if n.endswith((".mp4", ".m4a"))]
    assert names == []


def test_duplicate_and_delete_slide_with_movie(tmp_path, keynote_media):
    clip, _ = keynote_media
    deck = Presentation.new()
    deck.add_slide("Blank").add_movie(clip, position=(10, 10))
    deck.duplicate_slide(0)
    deck.delete_slide(0)
    again = reopen(deck, tmp_path)
    check_consistent(again)
    (m,) = again[0].movies
    assert m.data == clip


def test_movies_in_markdown(tmp_path, keynote_media):
    clip, tone = keynote_media
    (tmp_path / "clip.mp4").write_bytes(clip)
    (tmp_path / "tone.m4a").write_bytes(tone)
    md = """# A video

![A test pattern](clip.mp4)

---

![](clip.mp4 "100,100 320x180")
![](tone.m4a)
"""
    (first, second) = parse_markdown(md)
    assert first.default_layout() == "Title & Photo"
    deck = from_markdown(md, base_dir=str(tmp_path))
    assert deck[0].layout == "Title & Photo"
    (m,) = deck[0].movies
    assert m.placeholder == "Media" and m.description == "A test pattern"
    assert [(m.audio_only, m.size) for m in deck[1].movies] == [(False, (320, 180)), (True, (0, 0))]

    out = reopen(deck, tmp_path).to_markdown(image_dir=str(tmp_path / "media"))
    assert "![A test pattern](" in out and '"100,100 320x180")' in out
    assert (tmp_path / "media" / "clip.mp4").read_bytes() == clip
    assert (tmp_path / "media" / "tone.m4a").read_bytes() == tone
    again = from_markdown(out)
    assert [len(s.movies) for s in again] == [1, 2]
