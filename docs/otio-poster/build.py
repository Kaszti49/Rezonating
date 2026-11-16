"""Build the OTIO poster PDF (950 x 1350 mm) and check it against the organizer's print rules.

    python docs/otio-poster/build.py

Steps: fill poster.html with the images in images/ (placeholders for missing ones) and the
waveform from assets/waveform.json -> out/poster.html; ask headless Chrome for the print report
(smallest font, image px/cm, text outside the 3 cm safe zone); print the PDF; check its page size;
save a small preview PNG. Exits 1 if any rule fails, so a failing build is visible.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
PDF = OUT / "OTIO_poszter_Rezonating_Kaszti.pdf"
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
PAGE_MM = (950, 1350)
MIN_PX_PER_CM = 60      # organizer: 150 dpi at printed size
MIN_FONT_PT = 20        # organizer: body >= 28 pt, captions and references >= 20 pt

# id: (what it is, aspect ratio to generate, minimum pixels for 60 px/cm at its printed size)
IMAGES = {
    "H": ("Hero: cipő lép a padlón, csomópont", "2:1", "5700 x 2340"),
    "B": ("A Rezon szétszedve (robbantott nézet)", "16:9", "1500 x 800"),
    "D": ("Idősgondozás otthon", "2:1", "1700 x 850"),
    "E": ("Kamera helyett", "2:1", "1700 x 850"),
}


EXTS = (".jpg", ".jpeg", ".jfif", ".png", ".webp")
ALIASES = {"H": ("H", "Hero")}


def image_tag(key):
    """Use the widest file named <key>.* (or an alias), so an upscaled copy wins over the original."""
    from PIL import Image
    files = [f for f in (HERE / "images").glob("*") if f.suffix.lower() in EXTS
             and f.stem in ALIASES.get(key, (key,))]
    if files:
        f = max(files, key=lambda f: Image.open(f).size[0])
        return f'<img src="../images/{f.name}" alt="">'
    what, ratio, px = IMAGES[key]
    return (f'<div class="ph"><b>KÉP {key}</b>{what}<br>arány {ratio} · legalább {px} px'
            f'<br>prompt: PROMPTS.md</div>')


def wave_svg():
    d = json.loads((HERE / "assets/waveform.json").read_text())
    env, n = d["envelope"], len(d["envelope"])
    top = " ".join(f"{i},{100 - mx * 95:.1f}" for i, (mn, mx) in enumerate(env))
    bot = " ".join(f"{i},{100 - mn * 95:.1f}" for i, (mn, mx) in reversed(list(enumerate(env))))
    marks = "".join(f'<line x1="{s * n:.0f}" x2="{s * n:.0f}" y1="0" y2="200" class="mk"/>' for s in d["steps"])
    svg = (f'<svg viewBox="0 0 {n} 200" preserveAspectRatio="none">'
           '<style>.mk{stroke:var(--accent);stroke-width:1.6mm;vector-effect:non-scaling-stroke;opacity:.9}'
           '.ax{stroke:var(--rule);stroke-width:.4mm;vector-effect:non-scaling-stroke}</style>'
           f'<line x1="0" x2="{n}" y1="100" y2="100" class="ax"/>{marks}'
           f'<polygon points="{top} {bot}" fill="var(--ink)"/></svg>')
    secs = d["length_ms"] // 1000
    ticks = "".join(f'<span class="mono" style="left:{100 * k / secs:.2f}%">{k} s</span>' for k in range(1, secs))
    return svg + f'<div class="ticks">{ticks}</div>'


def chrome(*args):
    base = [str(CHROME), "--headless=new", "--disable-gpu", "--hide-scrollbars",
            "--allow-file-access-from-files", "--virtual-time-budget=15000"]
    return subprocess.run(base + list(args), capture_output=True, text=True, encoding="utf-8", timeout=300)


def main():
    OUT.mkdir(exist_ok=True)
    html = (HERE / "poster.html").read_text(encoding="utf-8")
    html = re.sub(r"\{\{IMG:(\w)\}\}", lambda m: image_tag(m.group(1)), html).replace("{{WAVE}}", wave_svg())
    page = OUT / "poster.html"
    page.write_text(html, encoding="utf-8")
    url = page.as_uri()
    fails = []

    dom = chrome("--dump-dom", url).stdout
    m = re.search(r'<script type="application/json" id="report">(.*?)</script>', dom, re.S)
    if not m:
        sys.exit("no print report in the rendered page (did the page load?)")
    rep = json.loads(m.group(1))
    print(f"smallest font: {rep['minFontPt']} pt  ({rep['minFontText']!r})")
    if rep["minFontPt"] < MIN_FONT_PT:
        fails.append(f"font below {MIN_FONT_PT} pt")
    for im in rep["images"]:
        ok = im["pxPerCm"] >= MIN_PX_PER_CM or "assets/" in im["src"] and "logo" in im["src"]
        print(f"image {im['src']}: {im['natural']} px over {im['printedMm']} mm = {im['pxPerCm']} px/cm"
              + ("" if ok else "  <-- below 60 px/cm"))
        if not ok:
            fails.append(f"image {im['src']} below {MIN_PX_PER_CM} px/cm")
    for u in rep["unsafe"]:
        print("outside 3 cm safe zone:", u)
        fails.append("text outside safe zone")
    missing = [k for k in IMAGES if 'class="ph"><b>KÉP ' + k in html]
    if missing:
        print("placeholders (image not in images/ yet):", ", ".join(missing))

    PDF.unlink(missing_ok=True)
    chrome("--no-pdf-header-footer", f"--print-to-pdf={PDF}", url)
    raw = PDF.read_bytes()
    box = re.search(rb"/MediaBox\s*\[\s*0 0 ([\d.]+) ([\d.]+)\s*\]", raw)
    pages = len(re.findall(rb"/Type\s*/Page[^s]", raw))
    w_mm, h_mm = (float(v) * 25.4 / 72 for v in box.groups())
    print(f"PDF: {PDF.name}, {pages} page(s), {w_mm:.1f} x {h_mm:.1f} mm, {len(raw) / 1e6:.1f} MB")
    if pages != 1 or abs(w_mm - PAGE_MM[0]) > 1 or abs(h_mm - PAGE_MM[1]) > 1:
        fails.append("PDF page size or count wrong")

    # preview at 1 px per mm (a screenshot of the page, for a quick look)
    shot = OUT / "preview.png"
    chrome(f"--screenshot={shot}", "--window-size=3591,5103", "--force-device-scale-factor=1", url)
    try:
        from PIL import Image
        Image.open(shot).resize((950, 1350)).save(OUT / "preview_small.png")
    except Exception as e:  # preview is a convenience, not a check
        print("preview resize skipped:", e)

    print("FAIL: " + "; ".join(fails) if fails else "PASS: page size, fonts, images, safe zone")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
