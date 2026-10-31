#!/usr/bin/env python3
"""Diagnostic : explore un site pour trouver où sont ses nouveautés.

Pour chaque site : page d'accueil, robots.txt, sitemaps annoncés par robots.txt,
puis les liens de la page d'accueil dont l'adresse évoque les nouveautés
(new, arrival, latest, just in, what...). Pour chaque page : statut, plateforme
probable, protection anti-robots éventuelle et nombre de blocs JSON-LD
(des données produits lisibles par machine).

Peu de requêtes, une pause entre chacune, jamais de contournement : un 403 ou un
404 veut dire « on ne passe pas par là ».

Usage :
    python collector/probe.py                       # sites par défaut
    python collector/probe.py https://exemple.com    # ajoute un site
Le résultat est affiché et, sur GitHub Actions, écrit dans le résumé de l'exécution.
"""
from __future__ import annotations

import os
import re
import sys
import time
from html import unescape
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
    body = resp.text[:2_000_000] if readable else ""
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


def main() -> None:
    sites = dict(SITES)
    for extra in sys.argv[1:]:
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
