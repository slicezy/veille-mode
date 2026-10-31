#!/usr/bin/env python3
"""Diagnostic : teste quelques pages publiques par site et dit ce qui répond.

Sert à comprendre pourquoi une marque échoue (mauvaise adresse, autre plateforme,
site qui bloque les accès automatiques). Peu de requêtes, une pause entre chacune,
et jamais de contournement : un 403 ou un 404 veut dire « on ne passe pas par là ».

Usage :
    python collector/probe.py                       # sites par défaut
    python collector/probe.py https://exemple.com    # ajoute un site
Le résultat est affiché et, sur GitHub Actions, écrit dans le résumé de l'exécution.
"""
from __future__ import annotations

import os
import sys
import time

import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; VeilleModePerso/1.0; usage personnel, faible volume)",
    "Accept-Language": "en,fr;q=0.8",
}
DELAY_SECONDS = 1.5

SITES = {
    "Meshki (AU)": "https://www.meshki.com.au",
    "Meshki (US)": "https://www.meshki.us",
    "Reformation": "https://www.thereformation.com",
    "Reformation (sans www)": "https://thereformation.com",
}
PATHS = [
    "/",
    "/robots.txt",
    "/sitemap.xml",
    "/collections/new-arrivals/products.json?limit=1",
    "/new-arrivals",
    "/whats-new",
]


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


def probe(site: str, path: str) -> dict:
    url = site.rstrip("/") + path
    try:
        resp = requests.get(url, headers=HEADERS, timeout=25, allow_redirects=True)
    except requests.RequestException as exc:
        return {"url": url, "status": "erreur", "type": "", "size": "", "tags": [], "final": str(exc)[:80]}
    ctype = resp.headers.get("content-type", "").split(";")[0]
    body = resp.text[:300000] if ("text" in ctype or "json" in ctype or "xml" in ctype) else ""
    return {
        "url": url,
        "status": resp.status_code,
        "type": ctype,
        "size": len(resp.content),
        "tags": fingerprint(resp.headers, body),
        "final": resp.url if resp.url != url else "",
    }


def main() -> None:
    sites = dict(SITES)
    for extra in sys.argv[1:]:
        sites[extra] = extra

    lines = [
        "| Site | Chemin | Statut | Type | Octets | Indices | Redirigé vers |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, site in sites.items():
        for path in PATHS:
            r = probe(site, path)
            lines.append(
                f"| {name} | `{path}` | {r['status']} | {r['type']} | {r['size']} | "
                f"{', '.join(r['tags'])} | {r['final']} |"
            )
            print(lines[-1], flush=True)
            time.sleep(DELAY_SECONDS)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("## Diagnostic des sites\n\n" + "\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
