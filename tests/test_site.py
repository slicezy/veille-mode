"""Test du rendu du site dans un vrai navigateur (Playwright + Chrome).

Lancer : python tests/test_site.py
Vérifie que les mots-clés, la palette et les cartes s'affichent, que les filtres
marchent, et que du contenu hostile (HTML, lien javascript:) est neutralisé.
"""
import functools
import http.server
import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent

DIGEST = {
    "title": "Noir, ivoire et argent",
    "summary": "Résumé de test.",
    "tags": ["dentelle", "soie", "argent", "maxi"],
    "palette": [
        {"name": "Noir", "hex": "#1F1E1C", "share": 40},
        {"name": "Ivoire", "hex": "#EFE8D8", "share": 25},
        {"name": "Beige", "hex": "#D8C8AE", "share": 15},
        {"name": "Camel", "hex": "#B58B5A", "share": 12},
        {"name": "Bordeaux", "hex": "#6D1F2E", "share": 8},
    ],
    "week_label": "Semaine du 26 octobre",
    "generated_at": "2026-10-30T22:00:00+00:00",
}


STATS = {
    "generated_at": "2026-10-30T22:00:00+00:00",
    "window_days": None,
    "total": 12,
    "with_photo_analysis": 12,
    "color_hex": {"noir": "#1F1E1C", "ivoire": "#EFE8D8", "beige": "#D8C8AE"},
    "types": [
        {"name": "Robes", "count": 6, "share": 50, "brands": 3},
        {"name": "Hauts", "count": 4, "share": 33, "brands": 2},
        {"name": "Accessoires", "count": 2, "share": 17, "brands": 1},
    ],
    "brands": [
        {"name": "Dissh", "count": 5, "currency": "AUD", "median_price": 189.0, "min_price": 99.0, "max_price": 320.0},
        {"name": "<b>Evil</b>", "count": 1, "currency": "ZZZ!"},
    ],
    "trends": [
        {"kind": "matière", "value": "satin", "brands": 3, "brand_names": ["Dissh", "Kookaï", "Sir."], "count": 7, "share": 58,
         "delta": 12, "new": False},
        {"kind": "détail", "value": "<img src=x onerror=window.__pwned=1>", "brands": 3, "brand_names": ["A", "B", "C"],
         "count": 3, "share": 25, "delta": 25, "new": True},
    ],
}
WEEKLY = {
    "depart": {"label": "30 oct.", "items": 12, "types": {"Robes": 6, "Hauts": 4, "Accessoires": 2}, "brands": {}},
    "weeks": [
        {"label": "26 oct.", "current": False, "items": 4, "types": {"Robes": 1, "Hauts": 3}, "brands": {"Dissh": {"new": 4}}},
        {"label": "2 nov.", "current": True, "items": 5, "types": {"Robes": 4, "Hauts": 1}, "brands": {"Dissh": {"new": 2}}},
    ],
}
TYPES = ["Robes", "Hauts", "Jupes"]


def make_items():
    items = []
    for brand in ["Dissh", "Kookaï", "Sir."]:
        for i in range(4):
            items.append(
                {
                    "id": f"{brand}{i}",
                    "brand": brand,
                    "name": f"Produit {brand} {i}",
                    "url": f"https://example.com/p/{i}",
                    "image": None,
                    "type": TYPES[i % 3],
                    "colors": ["noir", "multicolore"] if i == 0 else ["ivoire"],
                    "material": "satin",
                    "length": "midi",
                    "details": ["volants"],
                    "first_seen": "2026-10-30T12:00:00+00:00",
                }
            )
    items.append({"id": "acc", "brand": "Dissh", "name": "Sac invisible", "url": "https://example.com/p/acc",
                  "image": None, "type": "Accessoires", "first_seen": "2026-10-30T12:00:00+00:00"})
    items[0]["published_at"] = "2026-10-12T12:00:00+00:00"
    items.append(
        {
            "id": "evil",
            "brand": "Dissh",
            "name": "<img src=x onerror=window.__pwned=1>",
            "url": "javascript:window.__pwned=1",
            "image": None,
            "type": "Robes",
            "material": "<b>x</b>",
            "first_seen": "2026-10-30T12:00:00+00:00",
        }
    )
    return items


def main():
    items = make_items()
    tmp = Path(tempfile.mkdtemp())
    shutil.copytree(ROOT / "site", tmp, dirs_exist_ok=True)
    (tmp / "data").mkdir()
    (tmp / "data" / "digest.json").write_text(json.dumps(DIGEST), encoding="utf-8")
    (tmp / "data" / "stats.json").write_text(json.dumps(STATS), encoding="utf-8")
    (tmp / "data" / "weekly.json").write_text(json.dumps(WEEKLY), encoding="utf-8")
    (tmp / "data" / "items.json").write_text(json.dumps(items), encoding="utf-8")

    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args, **kwargs):
            pass

    handler = functools.partial(QuietHandler, directory=str(tmp))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"

    failures = []

    def check(cond, msg):
        if not cond:
            failures.append(msg)

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        # Les polices Google ne sont pas joignables ici : on les ignore.
        page.route("**/fonts.googleapis.com/**", lambda r: r.abort())
        page.goto(url)
        page.wait_for_selector(".card")

        text = page.inner_text("body")
        check("[object" not in text, "texte '[object ...]' affiché")
        check(page.locator(".tag").count() == 4, "4 mots-clés attendus")
        check(page.locator(".sw").count() == 5, "5 pastilles de palette attendues")
        check(page.locator(".card").count() == len(items) - 1, "toutes les cartes sauf l'accessoire attendues")
        check("Sac invisible" not in text, "accessoire affiché")
        check("Accessoires" not in page.inner_text("#types"), "filtre Accessoires affiché")
        check("mis en ligne 12 oct" in text.lower(), "date « Mis en ligne » attendue")
        check("repéré 30 oct" in text.lower(), "date « Repéré » attendue")
        check(page.locator(".nav a").count() == 2, "navigation attendue")
        check(page.locator("#brands .pill").count() == 4, "Toutes + 3 marques attendues")
        check(page.locator("#types .pill").count() == 5, "Tout + 3 types + Favoris attendus")
        check("Robes" in page.inner_text("#types") and "Sortie produit" not in page.inner_text("body"), "types attendus, plus d'ancienne catégorie")
        check("40 %" in page.inner_text(".palette-card") and "12 photos" in page.inner_text(".palette-card"), "parts de palette et base attendues")
        check(page.locator(".dot").count() >= len(items), "pastilles de couleur attendues")
        check(page.locator(".dot.multi").count() == 3, "pastille 'multicolore' attendue")
        check("satin · midi" in page.inner_text(".grid"), "ligne d'attributs attendue")
        check(page.locator(".attrs b").count() == 0, "HTML injecté dans les attributs")
        check(page.locator(".info img").count() == 0, "HTML injecté dans une carte")
        check(page.evaluate("window.__pwned") is None, "code injecté exécuté")
        hrefs = page.eval_on_selector_all(".info a", "els => els.map(e => e.getAttribute('href'))")
        check(all(h.startswith("https://") for h in hrefs), "lien non https affiché")
        check(len(hrefs) == len(items) - 2, "le lien javascript: doit être retiré")

        page.locator("#brands .pill", has_text="Sir.").click()
        check(page.locator(".card").count() == 4, "filtre Sir. : 4 cartes attendues")
        page.locator("#brands .pill", has_text="Toutes").click()
        page.locator("#types .pill", has_text="Jupes").click()
        check(page.locator(".card").count() == 3, "filtre Jupes : 3 cartes attendues")
        page.locator("#types .pill", has_text="Tout").first.click()
        page.locator(".heart").first.click()
        check("Favoris (1)" in page.inner_text("#types"), "compteur de favoris attendu")
        page.get_by_role("button", name="Favoris (1)").click()
        check(page.locator(".card").count() == 1, "filtre favoris : 1 carte attendue")
        check(not errors, f"erreurs JavaScript : {errors}")

        # Page « Chiffres »
        page.goto(url + "chiffres.html")
        page.wait_for_selector(".trend")
        body = page.inner_text("body")
        check("[object" not in body, "chiffres : texte '[object ...]' affiché")
        check("Répartition par type" in body and "Rythme et prix par marque" in body, "sections des chiffres attendues")
        check("Accessoires" not in body.replace("Les accessoires ne sont pas comptés", ""), "accessoires comptés dans les chiffres")
        check(page.locator(".bar-row").count() == 2, "2 types (sans accessoires) attendus")
        check("départ" in page.inner_text("#evolution").lower() and "en cours" in page.inner_text("#evolution").lower(), "colonnes départ et semaine en cours attendues")
        check(page.locator("#evolution tbody tr").count() == 7, "6 types + ligne des produits attendus")
        check("satin" in page.inner_text("#trends") and "+12 pts" in page.inner_text("#trends"), "tendance et écart attendus")
        check("nouveau" in page.inner_text("#trends"), "tendance nouvelle attendue")
        check("Kookaï, Sir." in page.inner_text("#trends") or "Dissh, Kookaï, Sir." in page.inner_text("#trends"), "marques de la tendance attendues")
        check("189" in page.inner_text("#brands") and "AUD" in page.inner_text("#brands"), "prix attendus avec devise")
        check(page.locator("#trends img, #brands b").count() == 0, "HTML injecté dans les chiffres")
        check(page.evaluate("window.__pwned") is None, "chiffres : code injecté exécuté")
        check(page.locator(".nav a[aria-current=page]").inner_text() == "Chiffres", "page courante attendue")
        check(not errors, f"erreurs JavaScript (chiffres) : {errors}")
        browser.close()

    server.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        for f in failures:
            print("ECHEC :", f)
        sys.exit(1)
    print("OK : le site s'affiche correctement")


if __name__ == "__main__":
    main()
