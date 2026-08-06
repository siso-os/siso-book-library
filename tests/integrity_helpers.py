from __future__ import annotations

import csv
from pathlib import Path

FIELDS = [
    "Text#", "Type", "Issued", "Title", "Language", "Authors", "Subjects",
    "LoCC", "Bookshelves",
]

def write_catalog(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

def row(
    gid: int, title: str, authors: str, subjects: str = "",
    locc: str = "", shelves: str = "",
) -> dict[str, str]:
    return {
        "Text#": str(gid), "Type": "Text", "Issued": "2001-01-01",
        "Title": title, "Language": "en", "Authors": authors,
        "Subjects": subjects, "LoCC": locc, "Bookshelves": shelves,
    }
