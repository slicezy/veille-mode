#!/usr/bin/env python3
"""Collecte les nouveautés des marques listées dans config/brands.json.

Pour chaque marque, les stratégies sont essayées dans l'ordre (par défaut :
shopify, jsonld, sitemap) et la première qui renvoie des produits est retenue.
Une marque en échec n'arrête jamais les autres : le détail est écrit dans
data/status.json.

Usage :
    python collector/collect.py              # toutes les marques
    python collector/collect.py --only meshki # une seule marque (debug)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import time
from html import unescape
from pathlib import Path
from urllib.parse import urljoin

import requests

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "brands.json"
DATA = ROOT / "data"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; VeilleModePerso/1.0; usage personnel, faible volume)",
    "Accept-Language": "en,fr;q=0.8",
}
DELAY_SECONDS = 2.0  # politesse : une requête toutes les 2 s
KEEP_DAYS = 60
MAX_PER_BRAND = 40

LD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I
)
LOC_RE = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.S)
URL_RE = re.compile(r"<url>(.*?)</url>", re.S)


def get(url: str) -> requests.Response:
    time.sleep(DELAY_SECONDS)
    resp = requests.get(url, headers=HEADERS, timeout=25)
    resp.raise_for_status()
    return resp


# --------------------------------------------------------------------------
# Stratégie 1 : Shopify (/collections/<handle>/products.json)
# --------------------------------------------------------------------------
def shopify_item(brand: dict, site: str, p: dict) -> dict:
    variants = p.get("variants") or []
    images = p.get("images") or []
    tags = p.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    return {
        "id": f"{brand['id']}:{p['id']}",
        "brand": brand["name"],
        "brand_id": brand["id"],
        "name": (p.get("title") or "").strip(),
        "url": f"{site}/products/{p['handle']}",
        "image": images[0].get("src") if images else None,
        "price": variants[0].get("price") if variants else None,
        "currency": brand.get("currency"),
        "published_at": p.get("published_at") or p.get("created_at"),
        "product_type": p.get("product_type") or "",
        "tags": tags,
    }


def strategy_shopify(brand: dict) -> list[dict]:
    site = brand["site"].rstrip("/")
    handles = brand.get("collections") or ["new-arrivals", "new", "new-in", "latest"]
    last_error: Exception | None = None
    for handle in handles:
        try:
            data = get(f"{site}/collections/{handle}/products.json?limit={MAX_PER_BRAND}").json()
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            continue
        products = data.get("products") or []
        if products:
            return [shopify_item(brand, site, p) for p in products[:MAX_PER_BRAND]]
    if last_error:
        raise last_error
    return []


# --------------------------------------------------------------------------
# Stratégie 2 : JSON-LD sur la page "nouveautés"
# --------------------------------------------------------------------------
def walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


def first_image(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value:
        return first_image(value[0])
    if isinstance(value, dict):
        return value.get("url") or value.get("contentUrl")
    return None


def offer_info(offers):
    if isinstance(offers, list) and offers:
        offers = offers[0]
    if isinstance(offers, dict):
        price = offers.get("price") or offers.get("lowPrice")
        return (str(price) if price is not None else None), offers.get("priceCurrency")
    return None, None


def parse_jsonld(brand: dict, site: str, page: str) -> list[dict]:
    found: dict[str, dict] = {}
    for block in LD_RE.findall(page):
        try:
            data = json.loads(unescape(block.strip()))
        except ValueError:
            continue
        for node in walk(data):
            kinds = node.get("@type")
            kinds = kinds if isinstance(kinds, list) else [kinds]
            if not ({"Product", "ListItem"} & set(k for k in kinds if isinstance(k, str))):
                continue
            name, url = node.get("name"), node.get("url")
            if not (name and url):
                continue
            url = urljoin(site + "/", url)
            if url in found:
                continue
            price, currency = offer_info(node.get("offers"))
            found[url] = {
                "id": f"{brand['id']}:{url}",
                "brand": brand["name"],
                "brand_id": brand["id"],
                "name": str(name).strip(),
                "url": url,
                "image": first_image(node.get("image")),
                "price": price,
                "currency": currency or brand.get("currency"),
                "published_at": None,
                "product_type": "",
                "tags": [],
            }
    return list(found.values())[:MAX_PER_BRAND]


def strategy_jsonld(brand: dict) -> list[dict]:
    site = brand["site"].rstrip("/")
    page_url = urljoin(site + "/", brand.get("new_path", "/new-arrivals").lstrip("/"))
    return parse_jsonld(brand, site, get(page_url).text)


# --------------------------------------------------------------------------
# Stratégie 3 : sitemap produits (dernier recours, 'lastmod' != date de sortie)
# --------------------------------------------------------------------------
def parse_sitemap(brand: dict, site: str, xml: str) -> list[dict]:
    rows = []
    for block in URL_RE.findall(xml):
        loc = LOC_RE.search(block)
        if not loc:
            continue
        lastmod = re.search(r"<lastmod>\s*(.*?)\s*</lastmod>", block, re.S)
        img = re.search(r"<image:loc>\s*(.*?)\s*</image:loc>", block, re.S)
        title = re.search(r"<image:title>\s*(.*?)\s*</image:title>", block, re.S)
        rows.append(
            (
                unescape(loc.group(1)),
                lastmod.group(1) if lastmod else "",
                unescape(img.group(1)) if img else None,
                unescape(title.group(1)) if title else None,
            )
        )
    product_rows = [r for r in rows if re.search(r"/(products?|p)/", r[0])] or rows
    product_rows.sort(key=lambda r: r[1], reverse=True)
    items = []
    for url, lastmod, img, title in product_rows[:MAX_PER_BRAND]:
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        name = title or slug.replace("-", " ").replace("_", " ").title()
        items.append(
            {
                "id": f"{brand['id']}:{url}",
                "brand": brand["name"],
                "brand_id": brand["id"],
                "name": name,
                "url": url,
                "image": img,
                "price": None,
                "currency": brand.get("currency"),
                "published_at": lastmod or None,
                "product_type": "",
                "tags": [],
            }
        )
    return items


def strategy_sitemap(brand: dict) -> list[dict]:
    site = brand["site"].rstrip("/")
    root_xml = get(site + "/sitemap.xml").text
    if "<sitemapindex" in root_xml:
        maps = [unescape(m) for m in LOC_RE.findall(root_xml)]
        maps = [m for m in maps if "product" in m.lower() and not m.endswith(".gz")][:2]
        xml = "".join(get(m).text for m in maps)
    else:
        xml = root_xml
    return parse_sitemap(brand, site, xml)


STRATEGIES = {
    "shopify": strategy_shopify,
    "jsonld": strategy_jsonld,
    "sitemap": strategy_sitemap,
}


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------
def parse_dt(value):
    if not value:
        return None
    try:
        d = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def sort_key(item: dict):
    floor = dt.datetime.min.replace(tzinfo=dt.timezone.utc)
    return parse_dt(item.get("published_at")) or parse_dt(item.get("first_seen")) or floor


def collect_brand(brand: dict) -> tuple[list[dict], dict]:
    errors = []
    for name in brand.get("strategies", ["shopify", "jsonld", "sitemap"]):
        try:
            found = STRATEGIES[name](brand)
        except Exception as exc:  # une marque ne doit jamais bloquer les autres
            errors.append(f"{name}: {exc}")
            continue
        if found:
            return found, {"ok": True, "strategy": name, "count": len(found), "errors": errors}
        errors.append(f"{name}: aucun produit")
    return [], {"ok": False, "strategy": None, "count": 0, "errors": errors}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="id d'une marque à collecter seule")
    args = parser.parse_args()

    brands = json.loads(CONFIG.read_text(encoding="utf-8"))["brands"]
    if args.only:
        brands = [b for b in brands if b["id"] == args.only]

    DATA.mkdir(exist_ok=True)
    items_path = DATA / "items.json"
    items = {}
    if items_path.exists():
        items = {i["id"]: i for i in json.loads(items_path.read_text(encoding="utf-8"))}

    now = dt.datetime.now(dt.timezone.utc)
    now_iso = now.isoformat(timespec="seconds")
    status = {"generated_at": now_iso, "brands": {}}

    for brand in brands:
        found, info = collect_brand(brand)
        new = 0
        for item in found:
            if item["id"] in items:
                items[item["id"]].update(
                    {k: item[k] for k in ("name", "url", "image", "price") if item.get(k)}
                )
            else:
                item["first_seen"] = now_iso
                items[item["id"]] = item
                new += 1
        info["new"] = new
        status["brands"][brand["id"]] = info
        print(f"{brand['name']}: {info['count']} produits ({info['strategy']}), {new} nouveaux")
        for err in info["errors"]:
            print(f"   - {err}")

    cutoff = now - dt.timedelta(days=KEEP_DAYS)
    kept = [
        i for i in items.values() if (parse_dt(i.get("first_seen")) or now) >= cutoff
    ]
    kept.sort(key=sort_key, reverse=True)

    items_path.write_text(json.dumps(kept, ensure_ascii=False, indent=1), encoding="utf-8")
    (DATA / "status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
