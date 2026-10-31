"""Tests hors ligne de la stratégie Reformation (liste JSON-LD + fiches produit)."""
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "collector"))

import collect  # noqa: E402

SITE = "https://www.thereformation.com"
BRAND = {
    "id": "reformation",
    "name": "Reformation",
    "site": SITE,
    "currency": "USD",
    "new_path": "/new/this-week",
    "max_enrich": 2,
}

# Forme réelle observée dans le rapport de diagnostic : adresses seulement.
URLS = [
    f"{SITE}/products/pepper-knit-top/1321206BLK.html",
    f"{SITE}/products/conroy-dress/1321177BLK.html",
    f"{SITE}/products/sandy-knit-dress/1321165POQ.html",
]
LIST_PAGE = (
    '<script type="application/ld+json">'
    + json.dumps(
        {
            "@context": "http://schema.org/",
            "@type": "ItemList",
            "itemListElement": [
                {"@type": "ListItem", "position": i + 1, "url": u} for i, u in enumerate(URLS)
            ],
        }
    )
    + "</script>"
)


def pdp(name, image, price):
    return (
        '<script type="application/ld+json">'
        + json.dumps(
            {
                "@type": "Product",
                "name": name,
                "image": [image],
                "offers": {"@type": "Offer", "price": price, "priceCurrency": "USD"},
            }
        )
        + "</script>"
    )


PAGES = {
    f"{SITE}/new/this-week": LIST_PAGE,
    URLS[0]: pdp("Pepper Knit Top", "https://cdn.example/pepper.jpg", "148.00"),
    URLS[1]: pdp("Conroy Dress", "//cdn.example/conroy.jpg", "278.00"),
}


class HelpersTests(unittest.TestCase):
    def test_itemlist_urls(self):
        self.assertEqual(collect.itemlist_urls(SITE, LIST_PAGE), URLS)

    def test_itemlist_accepts_item_forms_and_dedupes(self):
        page = (
            '<script type="application/ld+json">{"@type":"ItemList","itemListElement":['
            '{"item":"/products/a/1.html"},{"item":{"url":"/products/b/2.html"}},'
            '{"url":"/products/a/1.html"},"/products/c/3.html",42]}</script>'
        )
        self.assertEqual(
            collect.itemlist_urls(SITE, page),
            [f"{SITE}/products/a/1.html", f"{SITE}/products/b/2.html", f"{SITE}/products/c/3.html"],
        )

    def test_name_and_id_from_url(self):
        url = f"{SITE}/products/layla-silk-knee-length-skirt/1319019VRQ.html"
        self.assertEqual(collect.name_from_url(url), "Layla Silk Knee Length Skirt")
        self.assertEqual(collect.product_id(url), "1319019VRQ")

    def test_product_from_jsonld_ignores_other_blocks(self):
        html = '<script type="application/ld+json">{"@type":"BreadcrumbList"}</script>' + pdp(
            "Robe", "https://cdn.example/r.jpg", "99"
        )
        self.assertEqual(
            collect.product_from_jsonld(html),
            {"name": "Robe", "image": "https://cdn.example/r.jpg", "price": "99", "currency": "USD"},
        )
        self.assertEqual(collect.product_from_jsonld("<html></html>"), {})


class StrategyTests(unittest.TestCase):
    def run_strategy(self, pages, failing=()):
        calls = []

        def fake_get(url):
            calls.append(url)
            if url in failing:
                raise requests.RequestException("boom")
            return SimpleNamespace(text=pages.get(url, ""))

        with mock.patch.object(collect, "get", side_effect=fake_get):
            return collect.strategy_jsonld_pdp(BRAND), calls

    def test_enriches_only_first_products(self):
        items, calls = self.run_strategy(PAGES)
        self.assertEqual(len(items), 3)
        self.assertEqual(len(calls), 3)  # la liste + 2 fiches (max_enrich = 2)
        first, second, third = items
        self.assertEqual(first["id"], "reformation:1321206BLK")
        self.assertEqual(first["image"], "https://cdn.example/pepper.jpg")
        self.assertEqual(first["price"], "148.00")
        self.assertEqual(second["image"], "https://cdn.example/conroy.jpg")  # adresse relative complétée
        self.assertEqual(third["name"], "Sandy Knit Dress")  # nom tiré de l'adresse
        self.assertIsNone(third["image"])

    def test_product_page_failure_keeps_slug_name(self):
        items, _ = self.run_strategy(PAGES, failing={URLS[0]})
        self.assertEqual(items[0]["name"], "Pepper Knit Top")
        self.assertIsNone(items[0]["image"])
        self.assertEqual(items[1]["price"], "278.00")

    def test_empty_list_page_returns_nothing(self):
        items, _ = self.run_strategy({f"{SITE}/new/this-week": "<html></html>"})
        self.assertEqual(items, [])


if __name__ == "__main__":
    unittest.main()
