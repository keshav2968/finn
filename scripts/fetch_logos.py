"""Fetch each company's logo once, for the app's news cards, watchlist and stock pages.

    python scripts/fetch_logos.py                  # every company in config/portfolio.yaml
    python scripts/fetch_logos.py --symbols INFY,LT
    python scripts/fetch_logos.py --force          # replace logos already saved

For every company with a `domain` in config/portfolio.yaml, it tries free sources that need
no key and keeps the sharpest image:

  site        the company's own website: <link rel="apple-touch-icon" | "icon">, the web app
              manifest's icons, and /apple-touch-icon.png
  google      https://www.google.com/s2/favicons?domain=...&sz=256
  duckduckgo  https://icons.duckduckgo.com/ip3/<domain>.ico

"Sharpest" means the largest real size once transparent margins are trimmed; a tie goes to
the company's own site. Logos smaller than 128px are not saved, so the app shows the
monogram for that company instead of a blurry logo. Nothing is drawn or invented.

Writes, for the app (commit these):
  web/public/logos/SYMBOL.png     256px square (or the source's size if 128-255), transparent
  web/public/logos/sources.json   where each logo came from, its native size and any flags
For you to review before committing (git-ignored):
  data/cache/logos/contact-sheet.png   every logo on the app's light tile, with its source

The app never calls these sources at runtime: it serves the committed files from its own
domain. Logos are trademarks of their owners, shown for identification only.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402  (Pillow comes with pdfplumber)

from ingest.common import REPO_ROOT  # noqa: E402
from ingest.config import load_config  # noqa: E402

OUT_DIR = REPO_ROOT / "web" / "public" / "logos"
SHEET = REPO_ROOT / "data" / "cache" / "logos" / "contact-sheet.png"
MIN_PX = 128
TARGET_PX = 256
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"

Fetch = Callable[[str], "tuple[bytes, str] | None"]  # url -> (body, final url) or None


@dataclass
class Candidate:
    source: str
    url: str
    image: Image.Image
    native: int = 0          # the smaller side after trimming, in px
    flags: list[str] = field(default_factory=list)


def http_fetch(timeout: float = 12.0) -> Fetch:
    import requests

    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "*/*"})

    def get(url: str) -> tuple[bytes, str] | None:
        try:
            r = session.get(url, timeout=timeout, allow_redirects=True)
        except requests.RequestException as exc:
            print(f"    {url}: {type(exc).__name__}")
            return None
        if r.status_code != 200 or not r.content:
            print(f"    {url}: HTTP {r.status_code}")
            return None
        return r.content, r.url

    return get


class IconLinks(HTMLParser):
    """Collects <link rel=...icon...> hrefs (with declared sizes) and the manifest link."""

    def __init__(self) -> None:
        super().__init__()
        self.icons: list[tuple[str, int]] = []
        self.manifest: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "link":
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        rel = a.get("rel", "").lower()
        href = a.get("href", "")
        if not href:
            return
        if "manifest" in rel:
            self.manifest = href
        elif "icon" in rel:
            m = re.match(r"(\d+)x(\d+)", a.get("sizes", ""))
            self.icons.append((href, int(m.group(1)) if m else 0))


def decode(body: bytes) -> Image.Image | None:
    """PNG, JPEG, ICO (largest frame), WebP, GIF; SVG only if cairosvg is installed."""
    head = body[:400].lstrip().lower()
    if head.startswith(b"<svg") or head.startswith(b"<?xml") and b"<svg" in body[:2000].lower():
        try:
            import cairosvg  # optional

            body = cairosvg.svg2png(bytestring=body, output_width=512)
        except Exception:  # noqa: BLE001 - no SVG renderer: skip this candidate
            return None
    try:
        im = Image.open(io.BytesIO(body))
        if im.format == "ICO":
            sizes = sorted(im.info.get("sizes", []), key=lambda s: s[0] * s[1])
            if sizes:
                im.size = sizes[-1]
        im.load()
        return im.convert("RGBA")
    except Exception:  # noqa: BLE001 - not an image we can read
        return None


def trim(im: Image.Image) -> Image.Image:
    """Crop away fully transparent margins (a 16px logo padded to 256 is still 16px)."""
    box = im.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
    return im.crop(box) if box else im


def assess(c: Candidate) -> Candidate:
    t = trim(c.image)
    c.native = min(t.size)
    colours = len(set(t.convert("RGB").resize((32, 32)).getdata()))
    alpha = t.getchannel("A")
    opaque = sum(1 for a in alpha.resize((32, 32)).getdata() if a > 8) / 1024
    if c.native < MIN_PX:
        c.flags.append(f"small ({c.native}px)")
    if colours <= 2 or opaque < 0.03:
        c.flags.append("nearly blank")
    if c.source == "duckduckgo" and c.native <= 64:
        c.flags.append("favicon only")
    return c


def candidates(domain: str, get: Fetch) -> list[Candidate]:
    found: list[Candidate] = []

    def add(source: str, url: str) -> None:
        got = get(url)
        if not got:
            return
        im = decode(got[0])
        if im is not None and min(im.size) >= 16:
            found.append(assess(Candidate(source, url, im)))

    # 1. the company's own site
    home = get(f"https://{domain}/") or get(f"https://www.{domain}/")
    if home:
        body, base = home
        parser = IconLinks()
        try:
            parser.feed(body.decode("utf-8", "ignore"))
        except Exception:  # noqa: BLE001 - malformed HTML: use what was parsed
            pass
        for href, _size in sorted(parser.icons, key=lambda x: -x[1])[:4]:
            add("site", urljoin(base, href))
        if parser.manifest:
            man = get(urljoin(base, parser.manifest))
            if man:
                try:
                    icons = json.loads(man[0].decode("utf-8", "ignore")).get("icons", [])
                except ValueError:
                    icons = []
                def px(i: dict) -> int:
                    m = re.match(r"(\d+)", str(i.get("sizes", "")))
                    return int(m.group(1)) if m else 0
                for icon in sorted(icons, key=px, reverse=True)[:2]:
                    if icon.get("src"):
                        add("site", urljoin(man[1], icon["src"]))
        add("site", urljoin(base, "/apple-touch-icon.png"))
    # 2. Google's favicon service, 3. DuckDuckGo's icon service
    add("google", f"https://www.google.com/s2/favicons?domain={domain}&sz=256")
    add("duckduckgo", f"https://icons.duckduckgo.com/ip3/{domain}.ico")
    return found


def best(cands: list[Candidate]) -> Candidate | None:
    usable = [c for c in cands if "nearly blank" not in c.flags]
    if not usable:
        return None
    rank = {"site": 0, "google": 1, "duckduckgo": 2}
    return max(usable, key=lambda c: (c.native, -rank[c.source]))


def square(im: Image.Image) -> Image.Image:
    """The trimmed logo centred on a transparent square, at most TARGET_PX, never upscaled."""
    t = trim(im)
    side = max(t.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(t, ((side - t.width) // 2, (side - t.height) // 2), t)
    out = min(TARGET_PX, side)
    return canvas.resize((out, out), Image.LANCZOS) if out != side else canvas


def contact_sheet(rows: list[dict], path: Path) -> None:
    """Every company on the app's tile (white, rounded, padded) at card size and large."""
    cell_w, cell_h, cols = 300, 210, 4
    n = len(rows)
    sheet = Image.new("RGB", (cols * cell_w, ((n + cols - 1) // cols) * cell_h + 40), (23, 21, 29))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 15)
        small = ImageFont.truetype("DejaVuSans.ttf", 12)
    except OSError:
        font = small = ImageFont.load_default()
    d.text((12, 10), "FINN logos: check each one before committing (flags in orange)", fill=(243, 241, 247), font=font)

    def tile(size: int, logo: Image.Image | None) -> Image.Image:
        t = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ImageDraw.Draw(t).rounded_rectangle((0, 0, size - 1, size - 1), radius=size // 4, fill=(250, 250, 252))
        if logo is not None:
            pad = max(4, size // 7)
            inner = logo.copy()
            inner.thumbnail((size - 2 * pad, size - 2 * pad), Image.LANCZOS)
            t.paste(inner, ((size - inner.width) // 2, (size - inner.height) // 2), inner)
        return t

    for i, r in enumerate(rows):
        x, y = (i % cols) * cell_w + 12, (i // cols) * cell_h + 46
        logo = Image.open(r["file"]).convert("RGBA") if r.get("file") else None
        sheet.paste(tile(128, logo), (x, y), tile(128, logo))
        sheet.paste(tile(44, logo), (x + 140, y), tile(44, logo))
        d.text((x + 140, y + 54), r["symbol"], fill=(243, 241, 247), font=font)
        d.text((x + 140, y + 74), r.get("source") or "none", fill=(161, 155, 178), font=small)
        d.text((x + 140, y + 90), f"{r.get('native', 0)}px", fill=(161, 155, 178), font=small)
        if not logo:
            d.text((x + 34, y + 54), "monogram", fill=(161, 155, 178), font=font)
        for j, flag in enumerate(r.get("flags", [])[:3]):
            d.text((x, y + 136 + j * 16), flag, fill=(242, 160, 70), font=small)
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)


def run(symbols: list[str] | None, force: bool, get: Fetch, out_dir: Path = OUT_DIR, sheet: Path = SHEET) -> list[dict]:
    cfg = load_config()
    raw = __import__("yaml").safe_load((REPO_ROOT / "config" / "portfolio.yaml").read_text(encoding="utf-8"))
    domains = {str(c["symbol"]).upper(): c.get("domain") for c in raw.get("companies", [])}
    out_dir.mkdir(parents=True, exist_ok=True)
    prev_path = out_dir / "sources.json"
    sources = json.loads(prev_path.read_text(encoding="utf-8")) if prev_path.exists() else {}
    rows: list[dict] = []
    for sym, company in cfg.companies.items():
        if symbols and sym not in symbols:
            continue
        dest = out_dir / f"{sym}.png"
        domain = domains.get(sym)
        row: dict = {"symbol": sym, "name": company.name, "domain": domain}
        if dest.exists() and not force:
            row.update(sources.get(sym, {}), file=str(dest), kept=True)
            rows.append(row)
            print(f"{sym}: kept {dest.name} (use --force to refetch)")
            continue
        if not domain:
            print(f"{sym}: no domain in config/portfolio.yaml; monogram")
            rows.append({**row, "flags": ["no domain"]})
            continue
        print(f"{sym}: {domain}")
        cands = candidates(domain, get)
        for c in cands:
            print(f"    {c.source:<10} {c.native:>4}px {' '.join(c.flags)}  {c.url[:90]}")
        pick = best(cands)
        if pick is None or pick.native < MIN_PX:
            why = "nothing usable found" if pick is None else f"best is {pick.native}px (under {MIN_PX})"
            print(f"    -> monogram: {why}")
            if dest.exists():
                dest.unlink()
            sources.pop(sym, None)
            rows.append({**row, "source": pick.source if pick else None, "native": pick.native if pick else 0, "flags": (pick.flags if pick else []) + ["monogram"]})
            continue
        square(pick.image).save(dest, optimize=True)
        meta = {"source": pick.source, "url": pick.url, "native": pick.native, "flags": pick.flags}
        sources[sym] = meta
        rows.append({**row, **meta, "file": str(dest)})
        print(f"    -> {pick.source}, {pick.native}px -> {dest.relative_to(REPO_ROOT)}")
    prev_path.write_text(json.dumps(dict(sorted(sources.items())), indent=2) + "\n", encoding="utf-8")
    contact_sheet(rows, sheet)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--symbols", default="", help="comma-separated symbols (default: every company)")
    ap.add_argument("--force", action="store_true", help="refetch logos already saved")
    args = ap.parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] or None
    rows = run(symbols, args.force, http_fetch())
    saved = [r for r in rows if r.get("file")]
    print(f"\n{len(saved)} of {len(rows)} logos saved in web/public/logos; the rest show the monogram.")
    flagged = [r for r in rows if r.get("flags")]
    for r in flagged:
        print(f"  check {r['symbol']}: {', '.join(r['flags'])}")
    print(f"Contact sheet: {SHEET.relative_to(REPO_ROOT)}  (open it, then commit web/public/logos)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
