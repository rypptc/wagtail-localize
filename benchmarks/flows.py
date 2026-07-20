"""
The transversal catalog of wagtail-localize flows we evaluate, plus the data
setup they need. This declares WHAT we measure; each tool branch decides HOW.

It imports no measurement tool and measures nothing. Django is imported inside
the functions, so importing this module — and reading the catalog with
print_catalog() — stays cheap: no settings, no database, no tool required.
"""

from dataclasses import dataclass
from types import SimpleNamespace


# Fixed small scale. Big enough to fan out across snippets and locales, small
# enough to run in a second or two. No small/medium/large matrix on purpose —
# this is an initial probe, not a scaling sweep.
PAGES = 12
SNIPPETS = 4
# How many page translations to pre-create, so the report view renders several
# rows rather than a single one. Still small — a smoke test with a bit of body,
# not a scale sweep.
REPORT_PAGE_TRANSLATIONS = 5


@dataclass(frozen=True)
class Flow:
    """One flow we evaluate, plus the metadata that makes its coverage legible.

    `run` takes a prepared context (see prepare()) and drives the flow, returning
    the Django test-client response. `setup`, if given, runs against the context
    BEFORE measurement — for preconditions a tool shouldn't count. Everything
    else is documentation that print_catalog() prints verbatim.
    """

    name: str
    why: str
    entrypoint: str
    covers: tuple[str, ...]
    scale_dimensions: tuple[str, ...]
    run: object
    setup: object = None


# ---------------------------------------------------------------------------
# Data setup. Imports are deferred into these functions (not module-level) so
# importing this module and listing the catalog need no Django.
# ---------------------------------------------------------------------------


def _admin_client():
    """A logged-in superuser client, so admin views authorize normally."""
    from django.contrib.auth import get_user_model
    from django.test import Client

    user_model = get_user_model()
    user, _created = user_model.objects.update_or_create(
        username="benchmark-admin",
        defaults={
            "email": "benchmark-admin@example.com",
            "is_staff": True,
            "is_active": True,
            "is_superuser": True,
        },
    )
    client = Client()
    client.force_login(user)
    return client, user


def _create_translation(instance, target_locale, *, user=None):
    """Give `instance` a real, published target translation in `target_locale`,
    so update/report flows have an existing translation to act on.
    """
    from wagtail_localize.models import Translation, TranslationSource

    source, _created = TranslationSource.get_or_create_from_instance(instance)
    translation, _created = Translation.objects.get_or_create(
        source=source,
        target_locale=target_locale,
        defaults={"enabled": True},
    )
    translation.save_target(user=user, publish=True)
    return source, translation


def _touch_source_page(page):
    """Edit and publish the source page so its translation source is stale —
    which is what the update-translations flow exists to reconcile. Runs as a
    flow's `setup` (before measurement), not inside the measured block.
    """
    from django.utils import timezone

    page.test_charfield = f"Edited {timezone.now().isoformat()}"
    page.save_revision().publish()


def prepare():
    """Build fresh data for a single flow run.

    Called before every flow so results never depend on the order flows run in.
    Seeds a small tree with shared snippets, an admin client, and several pages
    and snippets already translated to French for the read/update flows.
    """
    from seed import build_snippet_pool, build_tree, ensure_locales, reset

    locales = ensure_locales()
    reset()
    snippets = build_snippet_pool(SNIPPETS, locales["en"])
    _home, pages = build_tree(PAGES, locales["en"], snippets)
    client, user = _admin_client()

    existing_page = pages[0]
    existing_page_source, existing_page_translation = _create_translation(
        existing_page, locales["fr"], user=user
    )
    # A handful more page translations plus a couple of snippets, so the report
    # view has several rows across content types — not a single one.
    for page in pages[1:REPORT_PAGE_TRANSLATIONS]:
        _create_translation(page, locales["fr"], user=user)
    for snippet in snippets[:2]:
        _create_translation(snippet, locales["fr"], user=user)

    return SimpleNamespace(
        locales=locales,
        client=client,
        user=user,
        pages=pages,
        snippets=snippets,
        existing_page=existing_page,
        existing_page_source=existing_page_source,
        existing_page_translation=existing_page_translation,
        # A page left untranslated, for the submit flow to create fresh.
        submit_page=pages[-1],
    )


# ---------------------------------------------------------------------------
# Flows. Each drives one real admin URL through the Django test client and
# returns the response. Only the action is here; preconditions live in `setup`.
# ---------------------------------------------------------------------------


def submit_page_post(ctx):
    from django.urls import reverse

    return ctx.client.post(
        reverse("wagtail_localize:submit_page_translation", args=[ctx.submit_page.id]),
        {"locales": [ctx.locales["fr"].id]},
    )


def update_translations_post_publish(ctx):
    from django.urls import reverse

    return ctx.client.post(
        reverse(
            "wagtail_localize:update_translations",
            args=[ctx.existing_page_source.id],
        ),
        {"publish_translations": "on"},
    )


def _update_translations_setup(ctx):
    """Precondition for update_translations_post_publish: make the source stale
    so the measured POST has real reconciliation work to do."""
    _touch_source_page(ctx.existing_page)


def translations_report_get(ctx):
    from django.urls import reverse

    return ctx.client.get(reverse("wagtail_localize:translations_report"))


# ---------------------------------------------------------------------------
# The catalog: what we evaluate and why. Three flows — one write (create), one
# write (update/publish), one read (report).
# ---------------------------------------------------------------------------

FLOW_CATALOG = [
    Flow(
        name="submit_page_post",
        why="Covers initial translation creation from the admin submit flow.",
        entrypoint="SubmitPageTranslationView.post/form_valid",
        covers=(
            "TranslationCreator.create_translations",
            "TranslationSource.get_or_create_from_instance",
            "TranslationSource.refresh_segments",
            "Translation.save_target",
            "copy_synchronised_fields",
        ),
        scale_dimensions=(
            "pages",
            "related snippets",
            "segments",
            "locales",
        ),
        run=submit_page_post,
    ),
    Flow(
        name="update_translations_post_publish",
        why="Covers updating an existing source and publishing existing target translations.",
        entrypoint="UpdateTranslationsView.form_valid",
        covers=(
            "TranslationSource.update_from_db",
            "TranslationSource.refresh_segments",
            "Translation.save_target",
            "copy_synchronised_fields",
        ),
        scale_dimensions=(
            "segments",
            "child objects",
            "locales",
        ),
        run=update_translations_post_publish,
        setup=_update_translations_setup,
    ),
    Flow(
        name="translations_report_get",
        why="Covers report/listing paths rather than write paths.",
        entrypoint="TranslationsReportView",
        covers=(
            "Translation.get_target_instance",
            "TranslationSource.get_source_instance",
            "TranslationSource.get_translated_instance",
        ),
        scale_dimensions=(
            "translations count",
            "content types",
            "locales",
        ),
        run=translations_report_get,
    ),
]

FLOWS_BY_NAME = {flow.name: flow for flow in FLOW_CATALOG}


def print_catalog():
    """Print the catalog so coverage is transparent without reading the code."""
    print("Flows evaluated by this benchmark:\n")
    for flow in FLOW_CATALOG:
        print(f"{flow.name}")
        print(f"    why:         {flow.why}")
        print(f"    entrypoint:  {flow.entrypoint}")
        print("    covers:")
        for name in flow.covers:
            print(f"        - {name}")
        print("    scale_dimensions:")
        for dimension in flow.scale_dimensions:
            print(f"        - {dimension}")
        print()
