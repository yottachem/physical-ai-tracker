"""Render the social preview card (site/static/social.png, 1200x630): 12-month closed equity by segment.

Run locally after the ledger moves the segment ranking; CI doesn't have Chrome, so the PNG is committed.
Run: uv run python site/social.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import build  # noqa: E402
from analysis import claims  # noqa: E402

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def bars(segs, width=640, row=40, label_w=300):
    top = max(s["raised"] for s in segs) or 1
    h = row * len(segs)
    out = [f'<svg class="chart" viewBox="0 0 {width} {h}" role="img" aria-label="Closed equity by segment, last 12 months">']
    for i, s in enumerate(segs):
        y = i * row
        w = max(2, (width - label_w - 90) * s["raised"] / top)
        out.append(f'<text class="lab" x="{label_w - 12}" y="{y + row / 2 + 5}" text-anchor="end">{s["short"]}</text>'
                   f'<rect x="{label_w}" y="{y + 9}" width="{w:.1f}" height="{row - 18}" class="bar"/>'
                   f'<text class="val" x="{label_w + w + 8:.1f}" y="{y + row / 2 + 5}">{s["usd"]}</text>')
    out.append("</svg>")
    return "".join(out)


def usd(v):
    return f"${v / 1e9:.1f}B" if v >= 1e9 else f"${v / 1e6:.0f}M" if v >= 1e6 else "$0"


SHORT = {"mobility": "Mobility and delivery", "defense": "Defense", "manufacturing_construction": "Manufacturing, construction",
         "foundation_models": "Foundation models", "warehouse_factory": "Warehouse and factory", "humanoids": "Humanoids",
         "lab_automation": "Lab automation", "consumer_home": "Consumer home", "healthcare": "Surgical and hospital",
         "wearables": "AI wearables", "agriculture": "Agriculture"}


def main():
    v = claims.current()
    segs = sorted(({"short": SHORT.get(k, x["name"]), "raised": x.get("raised_12m") or 0} for k, x in v.items()
                   if k != "market"), key=lambda s: -s["raised"])
    for s in segs:
        s["usd"] = usd(s["raised"])
    m = v["market"]
    html = Environment(loader=FileSystemLoader(HERE / "templates")).get_template("social.html.j2").render(
        chart=bars(segs), n=m["n"], segments=len(segs), raised=usd(m["raised_12m"]), site_url=build.SITE_URL)
    out = HERE / "static" / "social.png"
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "social.html"
        page.write_text(html)
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                        "--window-size=1200,630", "--virtual-time-budget=4000", f"--screenshot={out}", page.as_uri()],
                       check=True, capture_output=True)
    print(out)


if __name__ == "__main__":
    main()
