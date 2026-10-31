"""Tests hors ligne : collection « all » triée, cartes cadeaux, dates de sitemap, nettoyage d'une marque."""
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "collector"))

import collect  # noqa: E402
import purge  # noqa: E402

BRAND = {"id": "venroy", "name": "Venroy", "site": "https://venroy.example", "currency": "AUD",
         "strategies": ["shopify"], "collections": ["new-arrivals", "all"]}


def product(pid, title, ptype=""):
    return {"id": pid, "title": title, "handle": title.lower().replace(" ", "-"), "product_type": ptype,
            "published_at": "2026-10-20T00:00:00Z", "variants": [{"price": "120.00"}], "images": [{"src": "https://cdn.example/a.jpg"}]}


class ShopifyAllTests(unittest.TestCase):
    def run_collect(self, brand, responses):
        urls = []

        def fake_get(url):
            urls.append(url)
            for key, value in responses.items():
                if key in url:
                    if isinstance(value, Exception):
                        raise value
                    return SimpleNamespace(json=lambda v=value: v)
            raise requests.RequestException("404")

        with mock.patch.object(collect, "get", side_effect=fake_get):
            return collect.collect_brand(brand), urls

    def test_falls_back_to_all_sorted_by_creation(self):
        (found, info), urls = self.run_collect(BRAND, {
            "/collections/new-arrivals/": {"products": []},
            "/collections/all/": {"products": [product(1, "Silk Shirt")]},
        })
        self.assertEqual(info["strategy"], "shopify")
        self.assertEqual(found[0]["price"], "120.00")
        self.assertEqual(found[0]["source"], "shopify")
        self.assertIn("sort_by=created-descending", urls[-1])
        self.assertNotIn("sort_by", urls[0])

    def test_gift_cards_are_dropped(self):
        (found, _), _ = self.run_collect(BRAND, {"/collections/new-arrivals/": {"products": [
            product(1, "Gift Card"), product(2, "BENNI. Gift Card"), product(3, "Silk Dress"),
            product(4, "E-Gift Voucher"), product(5, "Wrap Top", "Gift Card")]}})
        self.assertEqual([i["name"] for i in found], ["Silk Dress"])  # seule la robe reste

    def test_only_gift_cards_means_no_products(self):
        (found, info), _ = self.run_collect(BRAND, {"/collections/": {"products": [product(1, "Gift Card")]}})
        self.assertEqual(found, [])
        self.assertFalse(info["ok"])


class SitemapDateTests(unittest.TestCase):
    def test_lastmod_is_not_a_publication_date(self):
        xml = '<urlset><url><loc>https://x.example/products/a</loc><lastmod>2026-11-01T00:00:00Z</lastmod></url></urlset>'
        item = collect.parse_sitemap({"id": "x", "name": "X", "currency": "AUD"}, "https://x.example", xml)[0]
        self.assertIsNone(item["published_at"])
        self.assertEqual(item["modified_at"], "2026-11-01T00:00:00Z")


class PurgeTests(unittest.TestCase):
    def test_purge_only_targeted_brands(self):
        items = [{"id": "venroy:https://v/a", "brand_id": "venroy"}, {"id": "henne:1", "brand_id": "henne"},
                 {"id": "dissh:9", "brand_id": "dissh"}]
        kept, removed = purge.purge_items(items, {"venroy", "henne"})
        self.assertEqual((removed, [i["id"] for i in kept]), (2, ["dissh:9"]))
        archive = [{"id": "venroy:https://v/a"}, {"id": "dissh:9"}, {"id": "sir:4"}]
        kept, removed = purge.purge_archive(archive, {"venroy"})
        self.assertEqual((removed, [a["id"] for a in kept]), (1, ["dissh:9", "sir:4"]))

    def test_brand_id_prefix_is_exact(self):
        kept, removed = purge.purge_archive([{"id": "sir:1"}, {"id": "sirius:2"}], {"sir"})
        self.assertEqual((removed, [a["id"] for a in kept]), (1, ["sirius:2"]))


if __name__ == "__main__":
    unittest.main()
