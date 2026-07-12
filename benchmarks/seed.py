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

from tests.testapp.models import TestHomePage, TestPage, TestSnippet  # noqa: E402


# The locales we translate against, and a fixed slug for the benchmark home so
# we can find and clear a previous run before reseeding.
TARGET_LANGUAGES = ["en", "fr", "es"]
HOME_SLUG = "bench-home"
# Pages are handed to categories in rotation (page 0 -> category 0, page 1 ->
# category 1, ...). We translate every 5th page. With 5 categories, every 5th
# page loops back to the same category, so all translations would stack in
# category 0. 4 categories spreads them out instead.
CATEGORY_COUNT = 4


def ensure_locales():
    """Make sure every locale we need exists. Idempotent (get_or_create)."""
    return {
        code: Locale.objects.get_or_create(language_code=code)[0]
        for code in TARGET_LANGUAGES
    }


def reset():
    """Remove a previous benchmark run so reseeding starts clean.

    Clears both the page tree and the related-object pool. benchmark.db is a
    dedicated database (gitignored, never the test suite's), so deleting all
    TestSnippets is safe — they only ever come from this seed.
    """
    # startswith, not an exact match: copy_for_translation suffixes the slug
    # per locale (e.g. "bench-home-fr") to avoid sibling slug collisions.
    for page in Page.objects.filter(slug__startswith=HOME_SLUG):
        page.delete()
    TestSnippet.objects.all().delete()


def build_snippet_pool(count, locale):
    """Create a pool of translatable snippets. Pages reference these (see
    build_tree), reusing snippets across pages the way a real site reuses
    shared content — which also gives the benchmark real related objects to
    exercise when translating.
    """
    return [
        TestSnippet.objects.create(
            field=f"Snippet {i} body — translatable text.",
            small_charfield=f"tag-{i}"[:10],
            locale=locale,
        )
        for i in range(count)
    ]


def build_tree(pages, locale, snippets):
    """Build a home page with `pages` child pages, organized under
    CATEGORY_COUNT categories (as a real site groups content, rather than
    hanging every page off one parent). Each page references a snippet from
    `snippets`, reusing the pool across pages the way a real site reuses
    shared content.

    Returns (home, pages): home for tree-level operations, and the flat list
    of leaf pages (home.get_children() returns the categories, not the pages).
    """
    root = Page.objects.get(depth=1)
    home = root.add_child(
        instance=TestHomePage(title="Bench Home", slug=HOME_SLUG, locale=locale)
    )
    categories = [
        home.add_child(
            instance=TestPage(
                title=f"Category {c}", slug=f"bench-category-{c}", locale=locale
            )
        )
        for c in range(CATEGORY_COUNT)
    ]

    pages_list = []
    for i in range(pages):
        category = categories[i % CATEGORY_COUNT]
        page = category.add_child(
            instance=TestPage(
                title=f"Page {i}",
                slug=f"bench-page-{i}",
                locale=locale,
                test_snippet=snippets[i % len(snippets)],
                test_richtextfield=(
                    f"<p>Body text for page {i}. This paragraph is "
                    f"translatable prose that produces a segment.</p>"
                ),
            )
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
    reset()
    snippets = build_snippet_pool(max(args.pages // 3, 1), locales["en"])
    home, pages = build_tree(args.pages, locales["en"], snippets)
    translate_some(pages, locales)

    print(
        f"Seeded {len(pages)} pages across {CATEGORY_COUNT} categories under '{home.slug}'."
    )
    print(f"Seeded {len(snippets)} snippets in the related-object pool.")
    # +2 vs. the seeded count: Wagtail's own migrations create the tree root
    # and a default "Welcome to your new Wagtail site!" page. We leave both
    # alone — the translation-sync operations under benchmark (synctree,
    # refresh_segments, save_target) never look at Site/root_page config.
    print(f"Total pages in tree: {Page.objects.count()}")


if __name__ == "__main__":
    main()
