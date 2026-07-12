"""
Seed a realistic page tree for scaling benchmarks.

This lives in benchmarks/ (outside src/) so it never ships with the package.
Run it with the repo's test settings and the repo venv, e.g.:

    DATABASE_URL=sqlite:///benchmark.db .venv/bin/python benchmarks/seed.py --pages 50
"""

import argparse

import env


env.bootstrap()

# Models can only be imported after env.bootstrap() has run.
from wagtail.models import Locale, Page  # noqa: E402

from tests.testapp.models import TestHomePage, TestPage  # noqa: E402


# The locales we translate against, and a fixed slug for the benchmark home so
# we can find and clear a previous run before reseeding.
TARGET_LANGUAGES = ["en", "fr", "es"]
HOME_SLUG = "bench-home"
# 4, not 5: translate_some() picks French pages via i % 5 == 0. If
# SECTION_COUNT shared that modulus, every French page would land in the
# same section (verified empirically 2026-07-12 — it did, with
# SECTION_COUNT=5). 4 is coprime with both 5 and 7 (the French/Spanish
# selection moduli), so translated/aliased pages spread across all sections.
SECTION_COUNT = 4


def ensure_locales():
    """Make sure every locale we need exists. Idempotent (get_or_create)."""
    return {
        code: Locale.objects.get_or_create(language_code=code)[0]
        for code in TARGET_LANGUAGES
    }


def reset_tree():
    """Remove a previous benchmark tree so reseeding starts from a clean state."""
    # startswith, not an exact match: copy_for_translation suffixes the slug
    # per locale (e.g. "bench-home-fr") to avoid sibling slug collisions.
    for page in Page.objects.filter(slug__startswith=HOME_SLUG):
        page.delete()


def build_tree(pages, locale):
    """Build a home page with `pages` child pages, spread across
    SECTION_COUNT section pages rather than all as direct children of home.

    This matters: a flat tree (all pages sharing one parent) makes every
    page's get_parent() call resolve to the exact same row, which some
    tools mistake for a fixable "duplicate query" — an artifact of the flat
    shape, not a property of the tool (verified against django-query-doctor,
    2026-07-12). Spreading pages across several sections gives each page a
    genuinely different parent, matching the shape wl-benchmark's own
    "realistic universe" seeder uses (multiple sections, each with its own
    articles) — unlike wl-benchmark's synctree-specific scaling script,
    which was flat in the same way this tree used to be.

    Returns (home, pages) — home for tree-level operations, pages as the
    flat list of leaf pages actually seeded (translate_some needs this list
    directly, since home.get_children() now returns sections, not pages).
    """
    root = Page.objects.get(depth=1)
    home = root.add_child(
        instance=TestHomePage(title="Bench Home", slug=HOME_SLUG, locale=locale)
    )
    sections = [
        home.add_child(
            instance=TestPage(
                title=f"Section {s}", slug=f"bench-section-{s}", locale=locale
            )
        )
        for s in range(SECTION_COUNT)
    ]

    pages_list = []
    for i in range(pages):
        section = sections[i % SECTION_COUNT]
        page = section.add_child(
            instance=TestPage(title=f"Page {i}", slug=f"bench-page-{i}", locale=locale)
        )
        pages_list.append(page)

    return home, pages_list


def translate_some(pages, locales):
    """Give the tree some multilingual content: translate every 5th page to
    French for real, and alias every 7th to Spanish. Most pages are left
    English-only, on purpose, to mirror a partially-translated site.
    """
    for i, page in enumerate(pages):
        if i % 5 == 0:
            page.copy_for_translation(locales["fr"], copy_parents=True)
        if i % 7 == 0:
            page.copy_for_translation(locales["es"], copy_parents=True, alias=True)


def main():
    parser = argparse.ArgumentParser(
        description="Seed a page tree for scaling benchmarks."
    )
    parser.add_argument(
        "--pages", type=int, default=50, help="number of child pages to create"
    )
    args = parser.parse_args()

    locales = ensure_locales()
    reset_tree()
    home, pages = build_tree(args.pages, locales["en"])
    translate_some(pages, locales)

    print(
        f"Seeded {len(pages)} pages across {SECTION_COUNT} sections under '{home.slug}'."
    )
    # +2 vs. the seeded count: Wagtail's own migrations create the tree root
    # and a default "Welcome to your new Wagtail site!" page. We leave both
    # alone — the translation-sync operations under benchmark (synctree,
    # refresh_segments, save_target) never look at Site/root_page config.
    print(f"Total pages in tree: {Page.objects.count()}")


if __name__ == "__main__":
    main()
