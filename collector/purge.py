#!/usr/bin/env python3
"""Retire des données tous les produits d'une ou plusieurs marques (items.json et archive.json).

À utiliser une fois quand une marque a été collectée par erreur avec la mauvaise méthode :
la prochaine collecte la reprend proprement. Ne touche à aucune autre marque.

  python collector/purge.py venroy henne benni
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"


def purge_items(items: list[dict], brand_ids: set[str]) -> tuple[list[dict], int]:
    kept = [i for i in items if i.get("brand_id") not in brand_ids and i.get("id", "").split(":", 1)[0] not in brand_ids]
    return kept, len(items) - len(kept)


def purge_archive(archive: list[dict], brand_ids: set[str]) -> tuple[list[dict], int]:
    kept = [a for a in archive if a.get("id", "").split(":", 1)[0] not in brand_ids]
    return kept, len(archive) - len(kept)


def main(argv: list[str]) -> int:
    ids = {a.strip().lower() for arg in argv for a in arg.split(",") if a.strip()}
    if not ids:
        print("Indique au moins une marque (son identifiant dans config/brands.json).")
        return 1
    for name, fn in (("items.json", purge_items), ("archive.json", purge_archive)):
        path = DATA / name
        if not path.exists():
            continue
        kept, removed = fn(json.loads(path.read_text(encoding="utf-8")), ids)
        indent = 1 if name == "items.json" else None
        path.write_text(
            json.dumps(kept, ensure_ascii=False, indent=indent, separators=None if indent else (",", ":")),
            encoding="utf-8",
        )
        print(f"{name} : {removed} produits retirés ({', '.join(sorted(ids))}), {len(kept)} restants")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
