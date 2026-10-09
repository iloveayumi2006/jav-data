from concurrent.futures import ThreadPoolExecutor

from PIL import Image

from jav_data.previews import cover_preview


def test_preview_is_bounded_cached_and_preserves_original(tmp_path):
    source = tmp_path / "original.jpg"
    Image.new("RGB", (2400, 1600), "red").save(source)
    original = source.read_bytes()
    with ThreadPoolExecutor(max_workers=4) as pool:
        paths = list(pool.map(lambda _: cover_preview(source, tmp_path / "data", 1), range(8)))
    assert len(set(paths)) == 1
    first = paths[0]
    with Image.open(first) as image:
        assert image.size == (768, 512)
    assert source.read_bytes() == original
    stamp = first.stat().st_mtime_ns
    assert cover_preview(source, tmp_path / "data", 1).stat().st_mtime_ns == stamp
    Image.new("RGB", (120, 180), "blue").save(source)
    refreshed = cover_preview(source, tmp_path / "data", 1)
    assert refreshed != first and not first.exists()
    with Image.open(refreshed) as image:
        assert image.size == (120, 180)
        assert image.getpixel((0, 0))[2] > 240
    assert not list(refreshed.parent.glob("*.tmp"))


def test_preview_keeps_portrait_orientation(tmp_path):
    source = tmp_path / "portrait.png"
    Image.new("RGB", (800, 1600), "white").save(source)
    with Image.open(cover_preview(source, tmp_path / "data", 2)) as image:
        assert image.size == (256, 512)
