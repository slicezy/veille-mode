"""Tests hors ligne : vérifient le parsing sur de petits exemples, sans réseau."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "collector"))

import analyze  # noqa: E402
import collect  # noqa: E402

BRAND = {"id": "demo", "name": "Demo", "site": "https://demo.example", "currency": "AUD"}

SHOPIFY = {
    "id": 123,
    "title": " Robe midi satin ",
    "handle": "robe-midi-satin",
    "published_at": "2026-10-28T10:00:00-04:00",
    "product_type": "Dresses",
    "tags": ["new", "satin"],
    "variants": [{"price": "189.00"}],
    "images": [{"src": "https://cdn.example/robe.jpg"}],
}

JSONLD_PAGE = """
<html><script type="application/ld+json">
{"@type":"ItemList","itemListElement":[
 {"@type":"ListItem","position":1,"item":{"@type":"Product","name":"Veste bouclée","url":"/p/veste-bouclee",
  "image":["https://cdn.example/veste.jpg"],"offers":{"price":"320","priceCurrency":"USD"}}},
 {"@type":"ListItem","position":2,"name":"Pantalon crêpe","url":"/p/pantalon-crepe"}
]}</script></html>
"""

SITEMAP = """
<urlset xmlns:image="x">
<url><loc>https://demo.example/products/old-top</loc><lastmod>2026-01-01</lastmod></url>
<url><loc>https://demo.example/products/new-coat</loc><lastmod>2026-10-29</lastmod>
 <image:image><image:loc>https://cdn.example/coat.jpg</image:loc></image:image></url>
<url><loc>https://demo.example/about</loc><lastmod>2026-10-30</lastmod></url>
</urlset>
"""


class CollectTests(unittest.TestCase):
    def test_shopify_item(self):
        item = collect.shopify_item(BRAND, BRAND["site"], SHOPIFY)
        self.assertEqual(item["id"], "demo:123")
        self.assertEqual(item["name"], "Robe midi satin")
        self.assertEqual(item["url"], "https://demo.example/products/robe-midi-satin")
        self.assertEqual(item["price"], "189.00")
        self.assertEqual(item["tags"], ["new", "satin"])

    def test_jsonld(self):
        items = collect.parse_jsonld(BRAND, BRAND["site"], JSONLD_PAGE)
        names = {i["name"] for i in items}
        self.assertEqual(names, {"Veste bouclée", "Pantalon crêpe"})
        veste = next(i for i in items if i["name"] == "Veste bouclée")
        self.assertEqual(veste["url"], "https://demo.example/p/veste-bouclee")
        self.assertEqual(veste["currency"], "USD")

    def test_sitemap_sorts_and_filters(self):
        items = collect.parse_sitemap(BRAND, BRAND["site"], SITEMAP)
        self.assertEqual([i["name"] for i in items], ["New Coat", "Old Top"])
        self.assertEqual(items[0]["image"], "https://cdn.example/coat.jpg")

    def test_sort_key_handles_missing_dates(self):
        items = [{"id": "a"}, {"id": "b", "published_at": "2026-10-01T00:00:00Z"}]
        items.sort(key=collect.sort_key, reverse=True)
        self.assertEqual(items[0]["id"], "b")


class AnalyzeTests(unittest.TestCase):
    def test_heuristic_category(self):
        self.assertEqual(analyze.heuristic_category({"name": "Capsule x Atelier"}), "Collab")
        self.assertEqual(analyze.heuristic_category({"name": "Lookbook hiver"}), "Collection")
        self.assertEqual(analyze.heuristic_category({"name": "Robe midi"}), "Sortie produit")

    def test_extract_json_with_noise(self):
        data = analyze.extract_json('Voici :\n```json\n[{"id": "a", "category": "Collab"}]\n```')
        self.assertEqual(data[0]["category"], "Collab")

    def test_classify_without_client_uses_rules(self):
        items = [{"id": "a", "name": "Drop automne"}, {"id": "b", "name": "Robe"}]
        analyze.classify(None, items)
        self.assertEqual([i["category"] for i in items], ["Collection", "Sortie produit"])

    def test_week_label(self):
        import datetime as dt

        self.assertEqual(analyze.week_label(dt.date(2026, 10, 30)), "Semaine du 26 octobre")


if __name__ == "__main__":
    unittest.main()
