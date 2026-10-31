"""Package the published site into a few files that can be hosted anywhere
static (or uploaded as one private page): index.html with the CSS and JS
inlined, plus the data merged into a handful of JSON chunks.

    python3 -m vexpredict.bundle --out dist [--seasons override]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import ROOT

SITE = ROOT / "site"
CHUNK_BYTES = 12_000_000


def build(out: Path, data_dir: Path | None = None, seasons: list[str] | None = None,
          title: str = "VexPredict", demo_me: int | None = None) -> dict:
    data_dir = data_dir or SITE / "data"
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("vp-data-*.json"):
        old.unlink()
    listed = json.loads((data_dir / "seasons.json").read_text())
    if seasons:
        listed = [s for s in listed if s["slug"] in seasons]
    files: dict[str, object] = {"seasons.json": listed}
    for s in listed:
        root = data_dir / s["slug"]
        for f in sorted(root.rglob("*.json")):
            files[str(f.relative_to(data_dir))] = json.loads(f.read_text())
    chunks: list[dict] = [{}]
    size = 0
    for k, v in files.items():
        n = len(json.dumps(v, separators=(",", ":")))
        if size + n > CHUNK_BYTES and chunks[-1]:
            chunks.append({})
            size = 0
        chunks[-1][k] = v
        size += n
    names = []
    for i, c in enumerate(chunks):
        name = f"vp-data-{i}.json"
        (out / name).write_text(json.dumps(c, separators=(",", ":")))
        names.append(name)
    html = (SITE / "index.html").read_text()
    body = html.split("<body>")[1].split("</body>")[0].replace('<script src="app.js"></script>', "")
    head_links = "\n".join(l for l in html.splitlines() if "fonts.g" in l)
    boot = f"window.__VP_CHUNKS = {json.dumps(names)};"
    if demo_me:
        boot += f" window.__VP_DEMO_ME = {int(demo_me)};"
    page = ('<meta charset="utf-8">\n'
            f"<title>{title}</title>\n"
            '<meta name="claude:viewport-fit-sides" content="cover">\n'
            f"{head_links}\n<style>\n{(SITE / 'style.css').read_text()}\n</style>\n{body}\n"
            f"<script>{boot}</script>\n<script>\n{(SITE / 'app.js').read_text()}\n</script>\n")
    (out / "index.html").write_text(page)
    return {"index": str(out / "index.html"), "chunks": names, "files": len(files),
            "bytes": sum((out / n).stat().st_size for n in names)}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "dist"))
    ap.add_argument("--seasons", nargs="*")
    ap.add_argument("--title", default="VexPredict")
    args = ap.parse_args(argv)
    print(build(Path(args.out), seasons=args.seasons, title=args.title))


if __name__ == "__main__":
    main()
