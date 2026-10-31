#!/usr/bin/env python3
"""Diagnostic : explore un site pour trouver où sont ses nouveautés.

Mode par défaut : pour chaque site, page d'accueil, robots.txt, sitemaps annoncés
par robots.txt, puis les liens de la page d'accueil dont l'adresse évoque les
nouveautés. Pour chaque page : statut, plateforme probable, protection
anti-robots éventuelle et nombre de blocs JSON-LD.

Mode --deep : analyse une page précise (ex. une liste de nouveautés) pour savoir
comment lire ses produits : JSON-LD, données intégrées, motifs de liens produit
et extrait HTML d'une vignette.

Peu de requêtes, une pause entre chacune, jamais de contournement : un 403 ou un
404 veut dire « on ne passe pas par là ».

Usage :
    python collector/probe.py                         # sites par défaut
    python collector/probe.py https://exemple.com      # ajoute un site
    python collector/probe.py --deep URL --out data/probe-report.md
Sur GitHub Actions, le tableau du mode par défaut est écrit dans le résumé.
"""
from __future__ import annotations

import argparse
import os
import re
import time
from collections import Counter
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; VeilleModePerso/1.0; usage personnel, faible volume)",
    "Accept-Language": "en,fr;q=0.8",
}
DELAY_SECONDS = 1.5
MAX_LINKS = 15
MAX_SITEMAPS = 4

SITES = {
    "Reformation": "https://www.thereformation.com",
}

KEYWORDS = re.compile(r"new|arrival|latest|just-?in|what", re.I)
HREF_RE = re.compile(r"""href=["']([^"'\s]+)["']""", re.I)
ASSET_RE = re.compile(r"\.(jpe?g|png|gif|webp|svg|css|js|ico|woff2?|pdf)$", re.I)
LD_RE = re.compile(
    r"""<script[^>]+type=["']application/ld\+json["'][^>]*>(.*?)</script>""", re.S | re.I
)
EMBEDDED_MARKERS = (
    "__NEXT_DATA__",
    "window.__INITIAL_STATE__",
    "__PRELOADED_STATE__",
    "dataLayer",
    'type="application/json"',
    "data-pid",
    "data-product",
)


def fingerprint(headers: dict, body: str) -> list[str]:
    """Indices sur la plateforme et sur une éventuelle protection anti-robots."""
    h = {k.lower(): str(v) for k, v in headers.items()}
    low = body.lower()
    server = h.get("server", "").lower()
    tags = []
    if "cloudflare" in server or "cf-ray" in h:
        tags.append("cloudflare")
    if "just a moment" in low or "cf-challenge" in low:
        tags.append("défi-cloudflare")
    if "akamai" in server or any(k.startswith("x-akamai") for k in h):
        tags.append("akamai")
    if "px-captcha" in low or "perimeterx" in low:
        tags.append("perimeterx")
    if "datadome" in low or "datadome" in h.get("set-cookie", "").lower():
        tags.append("datadome")
    if "cdn.shopify.com" in low or "x-shopid" in h or "x-shopify-stage" in h:
        tags.append("shopify")
    if "demandware" in low or "dwsid" in h.get("set-cookie", "").lower():
        tags.append("salesforce-commerce")
    return tags


def discover_links(site: str, html: str) -> list[str]:
    """Liens internes de la page dont l'adresse évoque les nouveautés."""
    host = urlparse(site).netloc.removeprefix("www.")
    found: list[str] = []
    for href in HREF_RE.findall(html):
        parts = urlparse(urljoin(site + "/", unescape(href)))
        if parts.netloc.removeprefix("www.") != host:
            continue
        if not parts.path or parts.path == "/" or ASSET_RE.search(parts.path):
            continue
        if not KEYWORDS.search(parts.path):
            continue
        url = parts._replace(query="", fragment="").geturl()
        if url not in found:
            found.append(url)
    return found[:MAX_LINKS]


def sitemap_urls(robots: str) -> list[str]:
    return re.findall(r"(?im)^\s*sitemap:\s*(\S+)", robots)[:MAX_SITEMAPS]


def fetch(url: str) -> tuple[dict, str]:
    time.sleep(DELAY_SECONDS)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=25, allow_redirects=True)
    except requests.RequestException as exc:
        row = {"url": url, "status": "erreur", "type": "", "size": "", "ld": "", "tags": [], "final": str(exc)[:80]}
        return row, ""
    ctype = resp.headers.get("content-type", "").split(";")[0]
    readable = "text" in ctype or "json" in ctype or "xml" in ctype
    body = resp.text[:3_000_000] if readable else ""
    row = {
        "url": url,
        "status": resp.status_code,
        "type": ctype,
        "size": len(resp.content),
        "ld": body.count("application/ld+json") if "html" in ctype else "",
        "tags": fingerprint(resp.headers, body[:300000]),
        "final": resp.url if resp.url != url else "",
    }
    return row, body


def run_site(name: str, site: str, out: list) -> None:
    site = site.rstrip("/")

    def add(url: str) -> str:
        row, body = fetch(url)
        out.append(
            f"| {name} | `{url}` | {row['status']} | {row['type']} | {row['size']} | "
            f"{row['ld']} | {', '.join(row['tags'])} | {row['final']} |"
        )
        print(out[-1], flush=True)
        return body

    home = add(site + "/")
    robots = add(site + "/robots.txt")
    for url in sitemap_urls(robots):
        add(url)
    for url in discover_links(site, home):
        add(url)


# --------------------------------------------------------------------------
# Mode --deep : comment lire les produits d'une page de liste
# --------------------------------------------------------------------------
def link_shape(path: str) -> tuple:
    """Forme d'une adresse : (premier segment, nombre de segments, finit par .html)."""
    segments = [s for s in path.split("/") if s]
    return (segments[0] if segments else "", len(segments), path.endswith(".html"))


def deep_report(url: str, body: str, snippet_before: int = 500, snippet_after: int = 1200) -> str:
    host = urlparse(url).netloc.removeprefix("www.")
    out = [f"# Analyse de {url}", "", f"- HTML : {len(body)} caractères"]
    markers = [m for m in EMBEDDED_MARKERS if m in body]
    out.append(f"- Marqueurs de données intégrées : {', '.join(markers) or 'aucun'}")

    blocks = LD_RE.findall(body)
    out.append(f"- Blocs JSON-LD : {len(blocks)}")
    for i, block in enumerate(blocks[:4], 1):
        out += ["", f"## JSON-LD n°{i} (début)", "```json", block.strip()[:1500], "```"]

    shapes: Counter = Counter()
    first_raw: dict = {}
    paths_by_shape: dict = {}
    for href in HREF_RE.findall(body):
        parts = urlparse(urljoin(url, unescape(href)))
        if parts.netloc.removeprefix("www.") != host:
            continue
        if not parts.path or parts.path == "/" or ASSET_RE.search(parts.path):
            continue
        shape = link_shape(parts.path)
        paths_by_shape.setdefault(shape, set()).add(parts.path)
        first_raw.setdefault(shape, href)
        shapes[shape] += 1

    out += ["", "## Formes d'adresses les plus fréquentes", "",
            "| Premier segment | Segments | .html | Adresses uniques | Exemple |", "|---|---|---|---|---|"]
    ranked = sorted(paths_by_shape.items(), key=lambda kv: len(kv[1]), reverse=True)[:8]
    for shape, paths in ranked:
        example = sorted(paths)[0]
        out.append(f"| {shape[0]} | {shape[1]} | {shape[2]} | {len(paths)} | `{example}` |")

    if ranked:
        shape = ranked[0][0]
        raw = first_raw[shape]
        idx = body.find(raw)
        if idx != -1:
            start = max(0, idx - snippet_before)
            snippet = body[start : idx + snippet_after]
            out += ["", "## Extrait HTML autour d'un lien de la forme la plus fréquente", "```html", snippet, "```"]
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sites", nargs="*", help="sites supplémentaires à explorer")
    parser.add_argument("--deep", metavar="URL", help="analyse approfondie d'une page")
    parser.add_argument("--out", metavar="FICHIER", help="écrit le rapport --deep dans ce fichier")
    args = parser.parse_args()

    if args.deep:
        row, body = fetch(args.deep)
        print(f"{args.deep} -> {row['status']} ({row['size']} octets)")
        report = deep_report(args.deep, body) if row["status"] == 200 else (
            f"# Analyse de {args.deep}\n\nStatut {row['status']} : page non lisible.\n"
        )
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(report, encoding="utf-8")
            print(f"Rapport écrit dans {args.out}")
        else:
            print(report)
        return

    sites = dict(SITES)
    for extra in args.sites:
        sites[extra] = extra

    lines = [
        "| Site | Adresse | Statut | Type | Octets | JSON-LD | Indices | Redirigé vers |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, site in sites.items():
        run_site(name, site, lines)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("## Diagnostic des sites\n\n" + "\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
