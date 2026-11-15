"""fetch_logos picks the sharpest real logo and never saves a small one (offline: fake fetcher)."""

import io
import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fetch_logos as F  # noqa: E402


def png(size: int, pad: int = 0) -> bytes:
    im = Image.new("RGBA", (size + 2 * pad, size + 2 * pad), (0, 0, 0, 0))
    inner = Image.new("RGBA", (size, size), (20, 90, 200, 255))
    for x in range(0, size, 4):  # some detail so it isn't "nearly blank"
        for y in range(size // 3):
            inner.putpixel((x, y), (240, 180, 30, 255))
    im.paste(inner, (pad, pad))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def fake(site_html: str, files: dict[str, bytes]):
    def get(url: str):
        if url in ("https://example.com/", "https://www.example.com/"):
            return (site_html.encode(), "https://example.com/") if site_html else None
        return (files[url], url) if url in files else None
    return get


def test_prefers_the_sharpest_and_trims_padding():
    html = '<html><head><link rel="icon" href="/fav.png"><link rel="apple-touch-icon" sizes="180x180" href="/touch.png"></head></html>'
    files = {
        "https://example.com/fav.png": png(32),
        "https://example.com/touch.png": png(180),
        "https://www.google.com/s2/favicons?domain=example.com&sz=256": png(64, pad=96),  # 256 canvas, 64px logo
    }
    cands = F.candidates("example.com", fake(html, files))
    pick = F.best(cands)
    assert pick.source == "site" and pick.native == 180
    google = next(c for c in cands if c.source == "google")
    assert google.native == 64 and any(f.startswith("small") for f in google.flags)


def test_small_logos_fall_back_to_the_monogram(tmp_path, monkeypatch):
    files = {"https://www.google.com/s2/favicons?domain=example.com&sz=256": png(48)}
    monkeypatch.setattr(F, "load_config", lambda: type("C", (), {"companies": {"EXMPL": type("Co", (), {"name": "Example"})()}})())
    yaml_path = tmp_path / "config" / "portfolio.yaml"
    yaml_path.parent.mkdir()
    yaml_path.write_text("companies:\n  - symbol: EXMPL\n    domain: example.com\n")
    monkeypatch.setattr(F, "REPO_ROOT", tmp_path)
    rows = F.run(None, True, fake("", files), out_dir=tmp_path / "logos", sheet=tmp_path / "sheet.png")
    assert not (tmp_path / "logos" / "EXMPL.png").exists()
    assert "monogram" in rows[0]["flags"]
    assert (tmp_path / "sheet.png").exists()
    assert json.loads((tmp_path / "logos" / "sources.json").read_text()) == {}


def test_saved_logo_is_square_and_never_upscaled(tmp_path):
    out = F.square(Image.open(io.BytesIO(png(150, pad=20))).convert("RGBA"))
    assert out.size == (150, 150)
    big = F.square(Image.open(io.BytesIO(png(400))).convert("RGBA"))
    assert big.size == (256, 256)
