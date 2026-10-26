"""Compile locale/*/LC_MESSAGES/django.po to .mo without GNU gettext (works on Windows)."""

from pathlib import Path

import polib

LOCALE_DIR = Path(__file__).resolve().parent.parent / "locale"


def main():
    for po_path in sorted(LOCALE_DIR.glob("*/LC_MESSAGES/django.po")):
        po = polib.pofile(str(po_path), encoding="utf-8")
        po.save_as_mofile(str(po_path.with_suffix(".mo")))
        print(f"{po_path.relative_to(LOCALE_DIR.parent)}: {len(po.translated_entries())} messages")


if __name__ == "__main__":
    main()
