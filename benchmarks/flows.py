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
# How many extra pages core_create_translations/core_synchronize_tree walk,
# on top of existing_page/submit_page (kept disjoint so flows don't collide).
CORE_PAGES = 5
# How many page translations to pre-create, so the report view renders several
# rows rather than a single one. Still small — a smoke test with a bit of body,
# not a scale sweep.
REPORT_PAGE_TRANSLATIONS = 5


@dataclass(frozen=True)
class Flow:
    """One flow we evaluate, plus the metadata that makes its coverage legible.

    `run` takes a prepared context (see prepare()) and drives the flow. Admin
    flows return the Django test-client response; core (operations-layer)
    flows return None — there's no HTTP status to report for those. `setup`,
    if given, runs against the context BEFORE measurement — for preconditions
    a tool shouldn't count. Everything else is documentation that
    print_catalog() prints verbatim.
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
    Seeds a small tree with shared snippets, an admin client, and a handful of
    pages/snippets already translated to French. Page and snippet slices are
    kept disjoint across roles (existing/report/core/submit) so flows don't
    collide with each other's preconditions:

        pages:    [0]        existing_page
                  [1:5]      extra report-only translations
                  [5:10]     core_pages (untouched by admin flows)
                  [11]       submit_page (left untranslated)
        snippets: [0]        existing_snippet
                  [1]        extra report-only translation
                  [3]        submit_snippet (left untranslated)
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
    existing_snippet = snippets[0]
    existing_snippet_source, existing_snippet_translation = _create_translation(
        existing_snippet, locales["fr"], user=user
    )

    # Extra translations so the report view has several rows across content
    # types, not just the "existing" ones above.
    for page in pages[1:REPORT_PAGE_TRANSLATIONS]:
        _create_translation(page, locales["fr"], user=user)
    _create_translation(snippets[1], locales["fr"], user=user)

    return SimpleNamespace(
        locales=locales,
        client=client,
        user=user,
        pages=pages,
        snippets=snippets,
        existing_page=existing_page,
        existing_page_source=existing_page_source,
        existing_page_translation=existing_page_translation,
        existing_snippet=existing_snippet,
        existing_snippet_source=existing_snippet_source,
        existing_snippet_translation=existing_snippet_translation,
        # Left untranslated, for the submit flows to create fresh.
        submit_page=pages[-1],
        submit_snippet=snippets[-1],
        # A slice untouched by the setup above, for the core operations flows.
        core_pages=pages[5 : 5 + CORE_PAGES],
    )


# ---------------------------------------------------------------------------
# Core flows: call the operations layer directly (no HTTP, no admin client).
# These return None — there's no response/status_code to report.
# ---------------------------------------------------------------------------


def core_create_translations(ctx):
    from wagtail_localize.operations import TranslationCreator

    creator = TranslationCreator(user=ctx.user, target_locales=[ctx.locales["es"]])
    for page in ctx.core_pages:
        creator.create_translations(page)


def core_synchronize_tree(ctx):
    from wagtail_localize.synctree import PageIndex, synchronize_tree

    # Mirror the sync_locale_trees management command: build the PageIndex once
    # and reuse it across every target locale, instead of rebuilding it per call.
    page_index = PageIndex.from_database().sort_by_tree_position()
    for target in (ctx.locales["fr"], ctx.locales["es"]):
        synchronize_tree(ctx.locales["en"], target, page_index=page_index)


def core_refresh_segments(ctx):
    ctx.existing_page_source.refresh_segments()


def core_save_target(ctx):
    ctx.existing_page_translation.save_target(user=ctx.user, publish=True)


# ---------------------------------------------------------------------------
# Admin flows. Each drives one real admin URL through the Django test client
# and returns the response. Only the action is here; preconditions live in
# `setup`.
# ---------------------------------------------------------------------------


def submit_page_get(ctx):
    from django.urls import reverse

    return ctx.client.get(
        reverse("wagtail_localize:submit_page_translation", args=[ctx.submit_page.id])
    )


def submit_page_post(ctx):
    from django.urls import reverse

    return ctx.client.post(
        reverse("wagtail_localize:submit_page_translation", args=[ctx.submit_page.id]),
        {"locales": [ctx.locales["fr"].id]},
    )


def submit_snippet_post(ctx):
    from django.urls import reverse

    model = type(ctx.submit_snippet)
    return ctx.client.post(
        reverse(
            "wagtail_localize:submit_snippet_translation",
            args=[model._meta.app_label, model._meta.model_name, ctx.submit_snippet.pk],
        ),
        {"locales": [ctx.locales["fr"].id]},
    )


def update_translations_get(ctx):
    from django.urls import reverse

    return ctx.client.get(
        reverse(
            "wagtail_localize:update_translations",
            args=[ctx.existing_page_source.id],
        )
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


# ---------------------------------------------------------------------------
# Report/API flows — read paths rather than write paths.
# ---------------------------------------------------------------------------


def translations_report_get(ctx):
    from django.urls import reverse

    return ctx.client.get(reverse("wagtail_localize:translations_report"))


def snippets_api_list(ctx):
    from django.urls import reverse

    model = type(ctx.existing_snippet)
    return ctx.client.get(
        reverse(
            "wagtail_localize:snippets_api_listing",
            args=[model._meta.app_label, model._meta.model_name],
        )
    )


# ---------------------------------------------------------------------------
# The catalog: what we evaluate and why.
#
# preview_translation was left out on purpose: exercising it correctly needs
# get_ephemeral_translated_instance + user_can_edit_instance + the target
# page's preview_modes lining up, which is more moving parts than the other
# flows here for one more read path. Not included until that's worth it.
# ---------------------------------------------------------------------------

FLOW_CATALOG = [
    Flow(
        name="core_create_translations",
        why="Covers the core translation-creation logic directly, without the admin view/HTTP layer around it.",
        entrypoint="wagtail_localize.operations.TranslationCreator.create_translations",
        covers=(
            "TranslationCreator.create_translations",
            "TranslationSource.get_or_create_from_instance",
            "TranslationSource.refresh_segments",
            "related-object fan-out (snippets referenced by pages)",
        ),
        scale_dimensions=(
            "pages",
            "related snippets",
            "segments",
        ),
        run=core_create_translations,
    ),
    Flow(
        name="core_synchronize_tree",
        why="Covers multi-locale tree sync the way the sync_locale_trees command runs it: one PageIndex built once and reused across every target locale.",
        entrypoint="wagtail_localize.management.commands.sync_locale_trees (shared PageIndex + synchronize_tree per locale)",
        covers=(
            "PageIndex.from_database",
            "PageIndex.sort_by_tree_position",
            "PageIndex reuse across target locales",
            "PageIndex.not_translated_into",
            "Page.copy_for_translation(alias=True)",
        ),
        scale_dimensions=("pages", "tree depth", "locales"),
        run=core_synchronize_tree,
    ),
    Flow(
        name="core_refresh_segments",
        why="Covers re-extracting segments from an existing, already-translated source.",
        entrypoint="wagtail_localize.models.TranslationSource.refresh_segments",
        covers=(
            "TranslationSource.refresh_segments",
            "segment extraction (StringSegment/TemplateSegment/RelatedObjectSegment)",
        ),
        scale_dimensions=("segments", "child objects"),
        run=core_refresh_segments,
    ),
    Flow(
        name="core_save_target",
        why="Covers writing a translated target instance from existing translations.",
        entrypoint="wagtail_localize.models.Translation.save_target",
        covers=(
            "Translation.save_target",
            "copy_synchronised_fields",
        ),
        scale_dimensions=("segments", "child objects"),
        run=core_save_target,
    ),
    Flow(
        name="submit_page_get",
        why="Covers rendering the submit-page-translation form.",
        entrypoint="SubmitPageTranslationView.get/get_context_data",
        covers=("SubmitTranslationForm construction",),
        scale_dimensions=("locales available",),
        run=submit_page_get,
    ),
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
        name="submit_snippet_post",
        why="Covers initial translation creation for a snippet rather than a page — a different admin entrypoint over the same core logic.",
        entrypoint="SubmitSnippetTranslationView.post/form_valid",
        covers=(
            "TranslationCreator.create_translations",
            "TranslationSource.get_or_create_from_instance",
            "Translation.save_target",
        ),
        scale_dimensions=("locales",),
        run=submit_snippet_post,
    ),
    Flow(
        name="update_translations_get",
        why="Covers rendering the update-translations form for an existing source.",
        entrypoint="UpdateTranslationsView.get/get_context_data",
        covers=("UpdateTranslationsForm construction",),
        scale_dimensions=("translations for this source",),
        run=update_translations_get,
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
    Flow(
        name="snippets_api_list",
        why="Covers the snippets listing API, a separate read path from the report view.",
        entrypoint="wagtail_localize.views.snippets_api.SnippetViewSet (list)",
        covers=("BaseSnippetSerializer listing",),
        scale_dimensions=("snippet count",),
        run=snippets_api_list,
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
