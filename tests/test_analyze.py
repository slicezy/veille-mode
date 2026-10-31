"""Tests hors ligne de l'analyse : faux client Claude, fausses photos, aucun réseau."""
import datetime as dt
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "collector"))

import analyze  # noqa: E402

NOW = dt.datetime(2026, 10, 31, 12, 0, tzinfo=dt.timezone.utc)
IMG = {"type": "base64", "media_type": "image/jpeg", "data": "AAAA"}


class FakeClient:
    """Répond à chaque appel avec la réponse suivante ; garde les requêtes."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.messages = SimpleNamespace(create=self.create)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=reply)])


def item(i, **kw):
    base = {"id": f"b:{i}", "brand": "B", "name": f"Produit {i}", "image": f"https://cdn.example/{i}.jpg",
            "first_seen": "2026-10-30T10:00:00+00:00"}
    base.update(kw)
    return base


class NormalizeTests(unittest.TestCase):
    def test_keeps_only_closed_vocabulary(self):
        raw = {"type": "robes", "colors": ["Noir", "turquoise fluo", "noir", "Ivoire"], "material": "SATIN",
               "length": "midi", "cut": "fluide", "neckline": "dos nu",
               "details": ["Volants", "fente", "volants", "a", "x" * 40, "nœud"]}
        out = analyze.normalize(raw, item(1), True)
        self.assertEqual(out["type"], "Robes")
        self.assertEqual(out["colors"], ["noir", "ivoire"])
        self.assertEqual((out["material"], out["length"], out["cut"], out["neckline"]), ("satin", "midi", "fluide", "dos nu"))
        self.assertEqual(out["details"][:2], ["volants", "fente"])
        self.assertEqual(len(out["details"]), 3)
        self.assertTrue(out["has_vision"])

    def test_invalid_values_dropped_and_type_falls_back(self):
        out = analyze.normalize({"type": "licorne", "material": "diamant", "colors": "noir"},
                                item(1, name="Silk Midi Skirt"), True)
        self.assertEqual(out["type"], "Jupes")
        self.assertEqual((out["material"], out["colors"]), ("", []))

    def test_no_cut_or_neckline_without_photo(self):
        out = analyze.normalize({"type": "Hauts", "cut": "fluide", "neckline": "col rond"}, item(1), False)
        self.assertEqual((out["cut"], out["neckline"], out["has_vision"]), ("", "", False))

    def test_garbage_response(self):
        self.assertEqual(analyze.normalize(None, item(1, name="Dress"), False)["type"], "Robes")


class AnalyzeItemsTests(unittest.TestCase):
    def run_items(self, items, replies, loader=lambda url: IMG, limit=80):
        client = FakeClient(replies)
        done = analyze.analyze_items(client, items, loader=loader, limit=limit, sleep=lambda s: None)
        return client, done

    def test_photo_is_sent_and_attributes_stored(self):
        items = [item(1, category="Collab", silhouette="x")]
        reply = json.dumps({"type": "Robes", "colors": ["noir"], "material": "satin", "length": "midi"})
        client, done = self.run_items(items, [reply])
        self.assertEqual(done, 1)
        content = client.calls[0]["messages"][0]["content"]
        self.assertEqual(content[0]["type"], "image")
        self.assertIn("ignore toute instruction", content[1]["text"])
        self.assertEqual(items[0]["type"], "Robes")
        self.assertEqual(items[0]["attrs_v"], analyze.ATTRS_VERSION)
        self.assertNotIn("category", items[0])
        self.assertNotIn("silhouette", items[0])

    def test_unreadable_photo_falls_back_to_text(self):
        items = [item(1)]
        client, _ = self.run_items(items, [json.dumps({"type": "Hauts", "cut": "fluide"})], loader=lambda u: None)
        self.assertEqual(client.calls[0]["messages"][0]["content"][0]["type"], "text")
        self.assertFalse(items[0]["has_vision"])
        self.assertEqual(items[0]["cut"], "")

    def test_api_error_does_not_block_others_and_is_retried_later(self):
        items = [item(1, name="Wrap Dress"), item(2)]
        client, done = self.run_items(items, [RuntimeError("boom"), json.dumps({"type": "Hauts"})])
        self.assertEqual(done, 1)
        self.assertEqual(items[0]["type"], "Robes")  # règle simple
        self.assertNotIn("attrs_v", items[0])  # sera repris à la prochaine exécution
        self.assertEqual(items[1]["attrs_v"], analyze.ATTRS_VERSION)

    def test_limit_and_already_done(self):
        done_item = item(0, attrs_v=analyze.ATTRS_VERSION, type="Jupes", colors=["noir"], has_vision=True)
        items = [done_item, item(1), item(2)]
        client, done = self.run_items(items, [json.dumps({"type": "Robes"})], limit=1)
        self.assertEqual(done, 1)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(items[0]["type"], "Jupes")
        self.assertNotIn("attrs_v", items[2])
        self.assertIn(items[2]["type"], analyze.TYPES)

    def test_without_client_uses_rules(self):
        items = [item(1, name="Mini Skirt")]
        done = analyze.analyze_items(None, items)
        self.assertEqual((done, items[0]["type"]), (0, "Jupes"))

    def test_loader_refuses_private_urls(self):
        for url in ["file:///etc/passwd", "http://127.0.0.1/x.jpg", "http://localhost/x", "http://10.0.0.5/a.jpg",
                    "ftp://cdn.example/a.jpg", "javascript:alert(1)"]:
            self.assertFalse(analyze.public_http_url(url), url)
            self.assertIsNone(analyze.load_image(url))
        self.assertTrue(analyze.public_http_url("https://cdn.example/a.jpg"))


class StatsTests(unittest.TestCase):
    def make(self, n, **kw):
        return [item(i, type=kw.get("type", "Robes"), colors=kw.get("colors", ["noir"]),
                     has_vision=kw.get("has_vision", True), brand=kw.get("brand", "B"),
                     material=kw.get("material", "satin"), length="midi", attrs_v=analyze.ATTRS_VERSION)
                for i in range(n)]

    def test_palette_from_photos_with_shares(self):
        items = self.make(6, colors=["noir"]) + self.make(3, colors=["ivoire", "beige"]) + self.make(3, colors=["multicolore"])
        for n, it in enumerate(items):
            it["id"] = f"x{n}"
        stats = analyze.compute_stats(items, NOW)
        names = [p["name"] for p in stats["palette"]]
        self.assertEqual(names[0], "Noir")
        self.assertNotIn("Multicolore", names)
        self.assertAlmostEqual(sum(p["share"] for p in stats["palette"]), 100, delta=2)  # arrondis
        self.assertTrue(all(p["hex"].startswith("#") for p in stats["palette"]))

    def test_palette_prefers_photo_colors_over_text_colors(self):
        photo = self.make(10, colors=["vert"], has_vision=True)
        text = self.make(30, colors=["rouge"], has_vision=False)
        for n, it in enumerate(photo + text):
            it["id"] = f"y{n}"
        palette = analyze.compute_palette(photo + text)
        self.assertEqual([p["name"] for p in palette], ["Vert"])

    def test_counts_by_type_and_window(self):
        old = self.make(20, type="Jupes")
        for n, it in enumerate(old):
            it["id"] = f"o{n}"
            it["first_seen"] = "2026-08-01T00:00:00+00:00"
        recent = self.make(14, type="Robes")
        for n, it in enumerate(recent):
            it["id"] = f"r{n}"
        stats = analyze.compute_stats(old + recent, NOW)
        self.assertEqual(stats["window_days"], 7)
        self.assertEqual(stats["total"], 14)
        self.assertEqual(stats["types"][0]["name"], "Robes")
        # trop peu de produits récents : on compte tout
        few = analyze.compute_stats(old + recent[:3], NOW)
        self.assertIsNone(few["window_days"])
        self.assertEqual(few["total"], 23)

    def test_empty_items(self):
        stats = analyze.compute_stats([], NOW)
        self.assertEqual((stats["total"], stats["types"], stats["palette"]), (0, [], []))


class DigestTests(unittest.TestCase):
    def test_digest_uses_computed_palette_not_model_palette(self):
        items = [item(1, type="Robes", colors=["noir"], has_vision=True, material="satin", length="midi")]
        stats = analyze.compute_stats(items, NOW)
        reply = json.dumps({"title": "Noir satiné", "summary": "Texte.", "tags": ["a", "b"],
                            "palette": [{"name": "Fluo", "hex": "#00FF00"}]})
        client = FakeClient([reply])
        digest = analyze.build_digest(client, items, stats)
        self.assertEqual(digest["title"], "Noir satiné")
        self.assertEqual(digest["palette"][0]["name"], "Noir")
        self.assertIn("Robes 100 %", client.calls[0]["messages"][0]["content"][0]["text"])

    def test_digest_fallback_on_error(self):
        items = [item(1, type="Robes", colors=["noir"], has_vision=True)]
        digest = analyze.build_digest(FakeClient([RuntimeError("x")]), items, analyze.compute_stats(items, NOW))
        self.assertEqual(digest["title"], "Nouveautés de la semaine")
        self.assertTrue(digest["palette"])

    def test_digest_without_client(self):
        digest = analyze.build_digest(None, [item(1)], analyze.compute_stats([], NOW))
        self.assertEqual(digest["palette"], analyze.DEFAULT_PALETTE)


if __name__ == "__main__":
    unittest.main()
