"""Planche d'inspiration (board) : une diapo par groupe de produits aux caractéristiques proches.

Format : bandeau (titre + filigrane), sous-titre du groupe, 11 photos numérotées (1 grande + 2 x 5).
Sortie : un fichier .pptx (à ouvrir dans PowerPoint ou à importer dans Google Slides).
Les photos sont téléchargées ici (réseau nécessaire : à lancer depuis GitHub Actions).
"""
import argparse
import datetime as dt
import io
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import analyze  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

SLOTS = 11
MIN_PARTIAL = 3  # en dessous, un groupe n'obtient pas de diapo
BOARD_TYPES = ["Pantalons", "Jeans", "Shorts", "Jupes", "Hauts", "Robes", "Blazers", "Manteaux"]
# Dimensions de regroupement, de la plus importante à la moins importante.
# Si un groupe précis n'a pas assez de produits, on retire la dernière dimension pour l'élargir.
DIMS = {
    "Pantalons": ["shape", "length", "rise", "style", "closure"],
    "Jeans": ["shape", "length", "rise"],
    "Shorts": ["shape", "length", "rise"],
    "Jupes": ["shape", "length", "rise", "style"],
    "Hauts": ["shape", "length", "style", "neckline"],
    "Robes": ["cut", "length", "style", "neckline"],
    "Blazers": ["shape", "length", "style"],
    "Manteaux": ["shape", "length", "style"],
}
FIRST_REQUIRED = {t: "shape" for t in BOARD_TYPES}
FIRST_REQUIRED["Robes"] = "cut"
IMAGE_DELAY = 1.0
LABELS_PATH = ROOT / "site" / "labels.json"
LANG = "fr"
_labels: dict | None = None


def labels() -> dict:
    """Traductions du site (site/labels.json) : une seule source pour le site et les planches."""
    global _labels
    if _labels is None:
        try:
            _labels = json.loads(LABELS_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _labels = {"values": {}, "ui": {}}
    return _labels


def tv(value: str) -> str:
    return labels().get("values", {}).get(value, value) if LANG == "en" else value


def tu(text: str, **params) -> str:
    s = labels().get("ui", {}).get(text, text) if LANG == "en" else text
    for k, val in params.items():
        s = s.replace("{" + k + "}", str(val))
    return s


DIM_LABEL = {"rise": lambda v: f"taille {v}", "length": lambda v: f"longueur {v}"}

# Mise en page, en pouces (diapo 16:9 de 10 x 5,625, comme Google Slides)
SLIDE_W, SLIDE_H = 10.0, 5.625
BANNER_H = 0.5
MARGIN = 0.3
GAP = 0.06
GRID_Y = 1.0
GRID_H = 4.3
BIG_W = 2.1


def cell_boxes() -> list[tuple[float, float, float, float]]:
    """Positions (x, y, largeur, hauteur) des 11 cases : 1 grande à gauche, puis 2 rangées de 5."""
    small_h = (GRID_H - GAP) / 2
    small_w = (SLIDE_W - 2 * MARGIN - BIG_W - 5 * GAP) / 5
    boxes = [(MARGIN, GRID_Y, BIG_W, GRID_H)]
    x0 = MARGIN + BIG_W + GAP
    for row in range(2):
        for col in range(5):
            boxes.append((x0 + col * (small_w + GAP), GRID_Y + row * (small_h + GAP), small_w, small_h))
    return boxes


# --- regroupement -------------------------------------------------------------


def candidates(items: list[dict], days: int, now: dt.datetime | None = None) -> list[dict]:
    """Produits utilisables : analysés avec photo lue, dans la période, avec une adresse de photo publique."""
    now = now or dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(days=days) if days else None
    out = []
    for i in items:
        if i.get("type") not in BOARD_TYPES or i.get("attrs_v") != analyze.ATTRS_VERSION or not i.get("has_vision"):
            continue
        if not analyze.public_http_url(i.get("image")):
            continue
        if not i.get(FIRST_REQUIRED[i["type"]]):
            continue
        if cutoff is not None:
            seen = analyze.item_date(i)
            if seen is None or seen < cutoff:
                continue
        out.append(i)
    return out


def interleave(items: list[dict]) -> list[dict]:
    """Du plus récent au plus ancien, en alternant les marques pour qu'une seule ne domine pas la diapo."""
    ordered = sorted(items, key=lambda i: str(i.get("first_seen") or ""), reverse=True)
    by_brand: dict[str, list[dict]] = {}
    for i in ordered:
        by_brand.setdefault(i.get("brand", ""), []).append(i)
    lanes = sorted(by_brand.values(), key=lambda lane: -len(lane))
    out = []
    while any(lanes):
        for lane in lanes:
            if lane:
                out.append(lane.pop(0))
    return out


def group_label(kind: str, key: tuple) -> str:
    parts = [tv(kind)]
    for dim, value in zip(DIMS[kind], key):
        if value:
            parts.append(tv(value) if LANG == "en" else DIM_LABEL.get(dim, lambda x: x)(value))
    return " · ".join(parts).upper()


def build_groups(items: list[dict]) -> list[dict]:
    """Renvoie une liste de diapos : {"kind", "label", "items" (11 au plus), "partial"}.

    Pour chaque type : on cherche d'abord des groupes complets (11 produits) selon toutes les dimensions,
    puis on élargit en retirant la dimension la moins importante, enfin on garde des groupes incomplets.
    """
    slides: list[dict] = []
    for kind in BOARD_TYPES:
        pool = [i for i in items if i.get("type") == kind]
        dims = DIMS[kind]
        for width in range(len(dims), 0, -1):
            last = width == 1
            groups: dict[tuple, list[dict]] = {}
            for i in pool:
                groups.setdefault(tuple(i.get(d) or "" for d in dims[:width]), []).append(i)
            for key, members in sorted(groups.items(), key=lambda kv: -len(kv[1])):
                ordered = interleave(members)
                full = len(ordered) // SLOTS
                chunks = [ordered[n * SLOTS:(n + 1) * SLOTS] for n in range(full)]
                rest = ordered[full * SLOTS:]
                if last and len(rest) >= MIN_PARTIAL:
                    chunks.append(rest)
                    rest = []
                # sinon le reste retourne dans le pool pour un regroupement plus large
                used = {id(i) for c in chunks for i in c}
                pool = [i for i in pool if id(i) not in used]
                for n, chunk in enumerate(chunks):
                    label = group_label(kind, key)
                    if len(chunks) > 1:
                        label += f" ({n + 1}/{len(chunks)})"
                    slides.append({"kind": kind, "label": label, "items": chunk, "partial": len(chunk) < SLOTS})
    return slides


# --- photos -------------------------------------------------------------------


def fetch_cell_image(url: str, size: tuple[float, float], getter=None) -> bytes | None:
    """Télécharge une photo et la recadre au format de sa case (en JPEG)."""
    from PIL import Image

    try:
        if getter is None:
            import requests

            resp = requests.get(url, timeout=20, headers={"User-Agent": "veille-mode/1.0"})
            resp.raise_for_status()
            raw = resp.content
        else:
            raw = getter(url)
        if len(raw) > analyze.IMAGE_MAX_BYTES:
            return None
        img = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception as exc:
        print(f"  photo illisible ({type(exc).__name__}) : {str(url)[:80]}")
        return None
    target = size[0] / size[1]
    w, h = img.size
    if w / h > target:  # trop large : on rogne les côtés
        new_w = int(h * target)
        img = img.crop(((w - new_w) // 2, 0, (w - new_w) // 2 + new_w, h))
    else:  # trop haute : on rogne en bas (le haut du vêtement reste visible)
        new_h = int(w / target)
        top = int((h - new_h) * 0.15)
        img = img.crop((0, top, w, top + new_h))
    img.thumbnail((int(size[0] * 220), int(size[1] * 220)))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=82)
    return buf.getvalue()


def collect_cells(slide: dict, spare: list[dict], getter=None, sleep=time.sleep, cache: dict | None = None) -> list[tuple[dict, bytes]]:
    """Récupère jusqu'à 11 photos lisibles ; une photo manquante est remplacée par le produit suivant du groupe."""
    cache = cache if cache is not None else {}
    boxes = cell_boxes()
    cells: list[tuple[dict, bytes]] = []
    for item in slide["items"] + spare:
        if len(cells) >= SLOTS:
            break
        _x, _y, w, h = boxes[len(cells)]
        url = item["image"]
        key = (url, round(w, 2), round(h, 2))
        if key not in cache:
            sleep(IMAGE_DELAY)
            cache[key] = fetch_cell_image(url, (w, h), getter)
        if cache[key]:
            cells.append((item, cache[key]))
    return cells


# --- PowerPoint ---------------------------------------------------------------

BANNER = (0xC8, 0xB8, 0x98)
INK = (0x2A, 0x29, 0x26)
MUTED = (0x7A, 0x76, 0x6E)
LIGHT = (0xF7, 0xF4, 0xEC)
FONT = "Calibri"


def money(item: dict, fx: dict | None) -> str:
    try:
        price = float(item.get("price"))
    except (TypeError, ValueError):
        return ""
    cad = analyze.to_cad(price, item.get("currency") or "CAD", fx)
    return f"{cad:.0f} $ CA" if cad is not None else ""


def safe_link(url) -> str | None:
    return str(url) if isinstance(url, str) and url.lower().startswith(("http://", "https://")) else None


def build_deck(slides_cells: list[tuple[dict, list[tuple[dict, bytes]]]], title: str, watermark: str, fx: dict | None, out: Path) -> None:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Inches, Pt

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(SLIDE_W), Inches(SLIDE_H)
    blank = prs.slide_layouts[6]
    boxes = cell_boxes()

    def text(slide, x, y, w, h, value, size, color, align=PP_ALIGN.LEFT, bold=False, name=None):
        box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        if name:
            box.name = name
        frame = box.text_frame
        frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
        frame.vertical_anchor = MSO_ANCHOR.MIDDLE
        frame.word_wrap = True
        para = frame.paragraphs[0]
        para.alignment = align
        run = para.add_run()
        run.text = value
        run.font.size, run.font.bold, run.font.name = Pt(size), bold, FONT
        run.font.color.rgb = RGBColor(*color)
        return box

    for meta, cells in slides_cells:
        slide = prs.slides.add_slide(blank)
        band = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, Inches(BANNER_H))
        band.name = "Bandeau"
        band.fill.solid()
        band.fill.fore_color.rgb = RGBColor(*BANNER)
        band.line.fill.background()
        band.shadow.inherit = False
        text(slide, MARGIN, 0, 6.5, BANNER_H, title.upper(), 16, LIGHT, name="Titre")
        if watermark:
            text(slide, SLIDE_W - MARGIN - 3.0, 0, 3.0, BANNER_H, watermark.upper(), 16, LIGHT, PP_ALIGN.RIGHT, name="Filigrane")
        text(slide, MARGIN, 0.58, SLIDE_W - 2 * MARGIN, 0.34, meta["label"], 15, INK, name="Sous-titre")

        notes = []
        for n, ((item, data), (x, y, w, h)) in enumerate(zip(cells, boxes), start=1):
            pic = slide.shapes.add_picture(io.BytesIO(data), Inches(x), Inches(y), Inches(w), Inches(h))
            pic.name = f"Photo {n}"
            label = f"{item.get('brand', '')} - {item.get('name', '')}".strip(" -")
            pic._element.nvPicPr.cNvPr.set("descr", label[:200])
            link = safe_link(item.get("url"))
            if link:
                pic.click_action.hyperlink.address = link
            tag = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x + w - 0.26), Inches(y + 0.04), Inches(0.22), Inches(0.2))
            tag.name = f"Numéro {n}"
            tag.fill.solid()
            tag.fill.fore_color.rgb = RGBColor(0x1F, 0x1E, 0x1C)
            tag.line.fill.background()
            tag.shadow.inherit = False
            frame = tag.text_frame
            frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
            frame.vertical_anchor = MSO_ANCHOR.MIDDLE
            para = frame.paragraphs[0]
            para.alignment = PP_ALIGN.CENTER
            run = para.add_run()
            run.text = str(n)
            run.font.size, run.font.name = Pt(9), FONT
            run.font.color.rgb = RGBColor(255, 255, 255)
            notes.append(f"{n}. {item.get('brand', '')} : {item.get('name', '')} {money(item, fx)} {item.get('url', '')}".strip())

        brands = sorted({c[0].get("brand", "") for c in cells if c[0].get("brand")})
        foot = ", ".join(brands)
        if meta["partial"]:
            foot = tu("Groupe incomplet : {n}/{m} produits. ", n=len(cells), m=SLOTS) + foot
        text(slide, MARGIN, GRID_Y + GRID_H + 0.08, SLIDE_W - 2 * MARGIN, 0.22, foot, 10, MUTED, name="Marques")
        slide.notes_slide.notes_text_frame.text = "\n".join(notes)
    prs.save(str(out))


def generate(items: list[dict], title: str, watermark: str, days: int, fx: dict | None, out: Path, getter=None, sleep=time.sleep) -> dict:
    pool = candidates(items, days)
    slides = build_groups(pool)
    built = []
    cache: dict = {}
    for meta in slides:
        cells = collect_cells(meta, [], getter, sleep, cache)
        if len(cells) >= MIN_PARTIAL:
            meta["partial"] = len(cells) < SLOTS
            built.append((meta, cells))
        else:
            print(f"  diapo « {meta['label']} » abandonnée : photos illisibles")
    if built:
        build_deck(built, title, watermark, fx, out)
    return {"candidates": len(pool), "slides": len(built), "partial": sum(1 for m, _ in built if m["partial"])}


def main() -> None:
    parser = argparse.ArgumentParser(description="Génère une planche .pptx à partir des produits analysés")
    parser.add_argument("--title", default="BIG IDEAS")
    parser.add_argument("--watermark", default="")
    parser.add_argument("--days", type=int, default=30, help="période (jours) ; 0 = tout l'historique gardé")
    parser.add_argument("--out", default="board.pptx")
    parser.add_argument("--lang", choices=["fr", "en"], default="fr", help="langue des sous-titres des diapos")
    args = parser.parse_args()
    global LANG
    LANG = args.lang
    items_path = DATA / "items.json"
    if not items_path.exists():
        sys.exit("data/items.json introuvable")
    items = json.loads(items_path.read_text(encoding="utf-8"))
    fx_path = DATA / "fx.json"
    fx = json.loads(fx_path.read_text(encoding="utf-8")) if fx_path.exists() else None
    pending = sum(1 for i in items if i.get("attrs_v") != analyze.ATTRS_VERSION)
    if pending:
        print(f"{pending} produits pas encore analysés avec les nouveaux attributs : ils ne figurent pas dans la planche.")
    result = generate(items, args.title, args.watermark, args.days, fx, Path(args.out))
    print(f"{result['candidates']} produits retenus, {result['slides']} diapos ({result['partial']} incomplètes).")
    if not result["slides"]:
        sys.exit("Aucune diapo : pas assez de produits analysés pour former un groupe (3 au moins).")


if __name__ == "__main__":
    main()
