"""
Flow driver: seed a realistic site, then run the real translation lifecycle
over it, so a tool watching can observe where queries pile up. Neutral — it
runs the whole flow and targets no specific operation.

    DATABASE_URL=sqlite:///benchmark.db .venv/bin/python benchmarks/flow.py
"""

import env


env.bootstrap()

from seed import (  # noqa: E402
    build_snippet_pool,
    build_tree,
    ensure_locales,
    reset,
    translate_some,
)

from wagtail_localize.operations import TranslationCreator  # noqa: E402
from wagtail_localize.synctree import synchronize_tree  # noqa: E402


PAGES = 30
SNIPPETS = 10


def run_flow(pages, locales):
    """Run the translation operations a real editor would trigger:
    submit each page for translation (which extracts segments and walks
    related objects), then sync the tree into each target locale.

    user is left None: it's only recorded for attribution and changes no
    query, so a benchmark has no reason to invent one.
    """
    creator = TranslationCreator(
        user=None, target_locales=[locales["fr"], locales["es"]]
    )
    for page in pages:
        creator.create_translations(page)

    synchronize_tree(locales["en"], locales["fr"])
    synchronize_tree(locales["en"], locales["es"])


def main():
    locales = ensure_locales()
    reset()
    snippets = build_snippet_pool(SNIPPETS, locales["en"])
    _home, pages = build_tree(PAGES, locales["en"], snippets)
    translate_some(pages, locales)

    run_flow(pages, locales)
    print(f"Ran the translation flow over {len(pages)} pages.")


if __name__ == "__main__":
    main()
