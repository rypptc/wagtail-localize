import json
import uuid

from unittest import mock

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from wagtail.blocks import StreamValue
from wagtail.models import Locale, Page, PageLogEntry

from tests.testapp.models import (
    TestChildObject,
    TestNonParentalChildObject,
    TestPage,
    TestRevisionsButNoDraftModel,
    TestSnippet,
    TestStreamBlock,
    TestSynchronizedChildObject,
)
from wagtail_localize.models import (
    MissingRelatedObjectError,
    MissingTranslationError,
    OverridableSegment,
    RelatedObjectSegment,
    SourceDeletedError,
    String,
    StringSegment,
    StringTranslation,
    Template,
    TemplateSegment,
    TranslationContext,
    TranslationSource,
)
from wagtail_localize.segments import (
    RelatedObjectSegmentValue,
    StringSegmentValue,
    TemplateSegmentValue,
)
from wagtail_localize.strings import StringValue


def create_test_page(**kwargs):
    parent = kwargs.pop("parent", None) or Page.objects.get(id=1)
    page = parent.add_child(instance=TestPage(**kwargs))
    page_revision = page.save_revision()
    page_revision.publish()
    page.refresh_from_db()

    source, created = TranslationSource.get_or_create_from_instance(page)

    prepare_source(source)

    return page


def prepare_source(source):
    # Recurse into any related objects
    for segment in source.relatedobjectsegment_set.all():
        if not isinstance(segment, RelatedObjectSegmentValue):
            continue

        related_source, created = TranslationSource.get_or_create_from_instance(
            segment.get_instance(source.locale)
        )
        prepare_source(related_source)


class TestGetOrCreateFromInstance(TestCase):
    def setUp(self):
        self.snippet = TestSnippet.objects.create(field="This is some test content")

    def test_create(self):
        source, created = TranslationSource.get_or_create_from_instance(self.snippet)

        self.assertTrue(created)
        self.assertEqual(source.object_id, self.snippet.translation_key)
        self.assertEqual(source.locale, self.snippet.locale)
        self.assertEqual(
            json.loads(source.content_json),
            {
                "pk": self.snippet.pk,
                "expire_at": None,
                "expired": False,
                "first_published_at": None,
                "go_live_at": None,
                "has_unpublished_changes": False,
                "last_published_at": None,
                "latest_revision": None,
                "live": True,
                "live_revision": None,
                "field": "This is some test content",
                "small_charfield": "",
                "test_snippet_orderable": [],
                "translation_key": str(self.snippet.translation_key),
                "locale": self.snippet.locale_id,
            },
        )
        self.assertTrue(source.created_at)

    def test_update(self):
        source = TranslationSource.objects.create(
            object_id=self.snippet.translation_key,
            specific_content_type=ContentType.objects.get_for_model(TestSnippet),
            locale=self.snippet.locale,
            content_json=json.dumps(
                {
                    "pk": self.snippet.pk,
                    "field": "Some different content",  # Changed
                    "small_charfield": "",
                    "translation_key": str(self.snippet.translation_key),
                    "locale": self.snippet.locale_id,
                }
            ),
            last_updated_at=timezone.now(),
        )

        new_source, created = TranslationSource.get_or_create_from_instance(
            self.snippet
        )

        self.assertEqual(source, new_source)
        self.assertEqual(
            json.loads(source.content_json)["field"], "Some different content"
        )
        self.assertEqual(
            json.loads(new_source.content_json)["field"], "Some different content"
        )


class TestUpdateOrCreateFromInstance(TestCase):
    def setUp(self):
        self.snippet = TestSnippet.objects.create(field="This is some test content")

    def test_create(self):
        source, created = TranslationSource.update_or_create_from_instance(self.snippet)

        self.assertTrue(created)
        self.assertEqual(source.object_id, self.snippet.translation_key)
        self.assertEqual(source.locale, self.snippet.locale)
        self.assertEqual(
            json.loads(source.content_json),
            {
                "pk": self.snippet.pk,
                "expire_at": None,
                "expired": False,
                "go_live_at": None,
                "has_unpublished_changes": False,
                "first_published_at": None,
                "last_published_at": None,
                "latest_revision": None,
                "live": True,
                "live_revision": None,
                "field": "This is some test content",
                "small_charfield": "",
                "test_snippet_orderable": [],
                "translation_key": str(self.snippet.translation_key),
                "locale": self.snippet.locale_id,
            },
        )
        self.assertTrue(source.created_at)

    def test_update(self):
        source = TranslationSource.objects.create(
            object_id=self.snippet.translation_key,
            specific_content_type=ContentType.objects.get_for_model(TestSnippet),
            locale=self.snippet.locale,
            content_json=json.dumps(
                {
                    "pk": self.snippet.pk,
                    "field": "Some different content",  # Changed
                    "small_charfield": "",
                    "translation_key": str(self.snippet.translation_key),
                    "locale": self.snippet.locale_id,
                }
            ),
            last_updated_at=timezone.now(),
        )

        new_source, created = TranslationSource.update_or_create_from_instance(
            self.snippet
        )

        self.assertFalse(created)

        self.assertEqual(source, new_source)
        self.assertEqual(
            json.loads(source.content_json)["field"], "Some different content"
        )
        self.assertEqual(
            json.loads(new_source.content_json)["field"], "This is some test content"
        )


class TestRevisionsButNoDraftModelGetOrCreateInstance(TestCase):
    def setUp(self):
        self.snippet = TestRevisionsButNoDraftModel.objects.create(
            field="This is some test content"
        )

    def test_create(self):
        source, created = TranslationSource.get_or_create_from_instance(self.snippet)

        self.assertTrue(created)
        self.assertEqual(source.object_id, self.snippet.translation_key)
        self.assertEqual(source.locale, self.snippet.locale)
        self.assertEqual(
            json.loads(source.content_json),
            {
                "pk": self.snippet.pk,
                "latest_revision": None,
                "field": "This is some test content",
                "translation_key": str(self.snippet.translation_key),
                "locale": self.snippet.locale_id,
            },
        )
        self.assertTrue(source.created_at)

    def test_update(self):
        source = TranslationSource.objects.create(
            object_id=self.snippet.translation_key,
            specific_content_type=ContentType.objects.get_for_model(
                TestRevisionsButNoDraftModel
            ),
            locale=self.snippet.locale,
            content_json=json.dumps(
                {
                    "pk": self.snippet.pk,
                    "field": "Some different content",  # Changed
                    "translation_key": str(self.snippet.translation_key),
                    "locale": self.snippet.locale_id,
                },
            ),
            last_updated_at=timezone.now(),
        )

        new_source, created = TranslationSource.get_or_create_from_instance(
            self.snippet
        )

        self.assertEqual(source, new_source)
        self.assertEqual(
            json.loads(source.content_json)["field"], "Some different content"
        )
        self.assertEqual(
            json.loads(new_source.content_json)["field"], "Some different content"
        )


class TestRevisionsButNoDraftModelUpdateOrCreateFromInstance(TestCase):
    def setUp(self):
        self.snippet = TestRevisionsButNoDraftModel.objects.create(
            field="This is some test content"
        )

    def test_create(self):
        source, created = TranslationSource.update_or_create_from_instance(self.snippet)

        self.assertTrue(created)
        self.assertEqual(source.object_id, self.snippet.translation_key)
        self.assertEqual(source.locale, self.snippet.locale)
        self.assertEqual(
            json.loads(source.content_json),
            {
                "pk": self.snippet.pk,
                "latest_revision": None,
                "field": "This is some test content",
                "translation_key": str(self.snippet.translation_key),
                "locale": self.snippet.locale_id,
            },
        )
        self.assertTrue(source.created_at)

    def test_update(self):
        source = TranslationSource.objects.create(
            object_id=self.snippet.translation_key,
            specific_content_type=ContentType.objects.get_for_model(
                TestRevisionsButNoDraftModel
            ),
            locale=self.snippet.locale,
            content_json=json.dumps(
                {
                    "pk": self.snippet.pk,
                    "field": "Some different content",  # Changed
                    "translation_key": str(self.snippet.translation_key),
                    "locale": self.snippet.locale_id,
                }
            ),
            last_updated_at=timezone.now(),
        )

        new_source, created = TranslationSource.update_or_create_from_instance(
            self.snippet
        )

        self.assertFalse(created)

        self.assertEqual(source, new_source)
        self.assertEqual(
            json.loads(source.content_json)["field"], "Some different content"
        )
        self.assertEqual(
            json.loads(new_source.content_json)["field"], "This is some test content"
        )


class TestAsInstanceForPage(TestCase):
    def setUp(self):
        self.page = create_test_page(title="Test page", slug="test-page")
        self.source, created = TranslationSource.get_or_create_from_instance(self.page)

    def test(self):
        # To show it actually is using the translation source and not the live object,
        # mess with the JSON content manually
        content = json.loads(self.source.content_json)

        content["title"] = "Changed title"
        self.source.content_json = json.dumps(content)
        self.source.save(update_fields=["content_json"])

        new_instance = self.source.as_instance()

        self.assertIsInstance(new_instance, TestPage)
        self.assertEqual(new_instance.id, self.page.id)
        self.assertEqual(new_instance.title, "Changed title")

    def test_raises_error_if_source_deleted(self):
        self.page.delete()

        with self.assertRaises(SourceDeletedError):
            self.source.as_instance()


class TestAsInstanceForSnippet(TestCase):
    def setUp(self):
        self.snippet = TestSnippet.objects.create(field="This is some test content")
        self.source, created = TranslationSource.get_or_create_from_instance(
            self.snippet
        )

    def test(self):
        # To show it actually is using the translation source and not the live object,
        # mess with the JSON content manually
        content = json.loads(self.source.content_json)

        content["field"] = "Some changed content"
        self.source.content_json = json.dumps(content)
        self.source.save(update_fields=["content_json"])

        new_instance = self.source.as_instance()

        self.assertIsInstance(new_instance, TestSnippet)
        self.assertEqual(new_instance.id, self.snippet.id)
        self.assertEqual(new_instance.field, "Some changed content")


class TestExportPO(TestCase):
    def setUp(self):
        self.page = create_test_page(
            title="Test page",
            slug="test-page",
            test_charfield="This is some test content",
            test_textfield="This is some test content",
        )
        self.source, created = TranslationSource.get_or_create_from_instance(self.page)

    def test_export_po(self):
        po = self.source.export_po()

        self.assertEqual(
            po.metadata.keys(), {"POT-Creation-Date", "MIME-Version", "Content-Type"}
        )
        self.assertEqual(po.metadata["MIME-Version"], "1.0")
        self.assertEqual(po.metadata["Content-Type"], "text/plain; charset=utf-8")

        self.assertEqual(len(po), 2)
        self.assertEqual(po[0].msgid, "This is some test content")
        self.assertEqual(po[0].msgctxt, "test_charfield")
        self.assertEqual(po[0].msgstr, "")
        self.assertFalse(po[0].obsolete)

        # Test with the exact same content twice
        # This checks for https://github.com/wagtail/wagtail-localize/issues/253
        self.assertEqual(po[1].msgid, "This is some test content")
        self.assertEqual(po[1].msgctxt, "test_textfield")
        self.assertEqual(po[1].msgstr, "")
        self.assertFalse(po[1].obsolete)


class TestCreateOrUpdateTranslationForPage(TestCase):
    def setUp(self):
        self.snippet = TestSnippet.objects.create(field="Test snippet content")
        self.page = create_test_page(
            title="Test page",
            slug="test-page",
            test_charfield="This is some test content",
            test_snippet=self.snippet,
        )
        self.source, created = TranslationSource.get_or_create_from_instance(self.page)
        self.source_locale = Locale.objects.get(language_code="en")
        self.dest_locale = Locale.objects.create(language_code="fr")

        # Translate the snippet
        self.translated_snippet = self.snippet.copy_for_translation(self.dest_locale)
        self.translated_snippet.field = "Tester le contenu de l'extrait"
        self.translated_snippet.save()

        # Add translation for test_charfield
        self.string = String.from_value(
            self.source_locale, StringValue.from_plaintext("This is some test content")
        )
        self.translation = StringTranslation.objects.create(
            translation_of=self.string,
            locale=self.dest_locale,
            context=TranslationContext.objects.get(
                object_id=self.page.translation_key, path="test_charfield"
            ),
            data="Ceci est du contenu de test",
        )

    def test_create(self):
        new_page, created = self.source.create_or_update_translation(self.dest_locale)

        self.assertTrue(created)
        self.assertEqual(new_page.title, "Test page")
        self.assertEqual(new_page.slug, "test-page-fr")
        self.assertEqual(new_page.test_charfield, "Ceci est du contenu de test")
        self.assertEqual(new_page.translation_key, self.page.translation_key)
        self.assertEqual(new_page.locale, self.dest_locale)
        self.assertTrue(
            self.source.translation_logs.filter(locale=self.dest_locale).exists()
        )

    def test_create_finds_available_slug(self):
        # Create a page with the `test-page-fr` slug already
        create_test_page(
            title="Test Page FR",
            slug="test-page-fr",
        )

        new_page, created = self.source.create_or_update_translation(self.dest_locale)

        self.assertTrue(created)
        self.assertEqual(new_page.slug, "test-page-fr-1")

    def test_create_child(self):
        child_page = create_test_page(
            title="Child page",
            slug="child-page",
            parent=self.page,
            test_charfield="This is some test content",
            test_snippet=self.snippet,
        )
        child_source, created = TranslationSource.get_or_create_from_instance(
            child_page
        )

        translated_parent = self.page.copy_for_translation(self.dest_locale)

        # Create a translation for the new context
        StringTranslation.objects.create(
            translation_of=self.string,
            locale=self.dest_locale,
            context=TranslationContext.objects.get(
                object_id=child_page.translation_key, path="test_charfield"
            ),
            data="Ceci est du contenu de test",
        )

        new_page, created = child_source.create_or_update_translation(self.dest_locale)

        self.assertTrue(created)
        self.assertEqual(new_page.get_parent(), translated_parent)
        self.assertEqual(new_page.title, "Child page")
        self.assertEqual(new_page.test_charfield, "Ceci est du contenu de test")
        self.assertEqual(new_page.test_snippet, self.translated_snippet)
        self.assertEqual(new_page.translation_key, child_page.translation_key)
        self.assertEqual(new_page.locale, self.dest_locale)
        self.assertTrue(
            child_source.translation_logs.filter(locale=self.dest_locale).exists()
        )

    def test_update(self):
        self.page.copy_for_translation(self.dest_locale)

        new_page, created = self.source.create_or_update_translation(self.dest_locale)

        self.assertFalse(created)
        self.assertEqual(new_page.title, "Test page")
        self.assertEqual(new_page.test_charfield, "Ceci est du contenu de test")
        self.assertEqual(new_page.test_snippet, self.translated_snippet)
        self.assertEqual(new_page.translation_key, self.page.translation_key)
        self.assertEqual(new_page.locale, self.dest_locale)
        self.assertTrue(
            self.source.translation_logs.filter(locale=self.dest_locale).exists()
        )

    def test_update_synchronised_fields(self):
        # Add a couple of initial child objects.
        # The first one will be deleted in the source page after initial translation. The sync should carry this deletion across.
        # The second won't be deleted so should remain in the translation
        self.page.test_synchronized_childobjects.add(
            TestSynchronizedChildObject(
                field="Test child object that existed before initial translation and was deleted"
            )
        )

        self.page.test_synchronized_childobjects.add(
            TestSynchronizedChildObject(
                field="Test child object that existed before initial translation and was not deleted"
            )
        )

        translated = self.page.copy_for_translation(self.dest_locale)

        self.page.test_synchronized_charfield = "Test synchronised content"
        self.page.test_synchronized_textfield = "Test synchronised content"
        self.page.test_synchronized_emailfield = "test@synchronised.content"
        self.page.test_synchronized_slugfield = "test-synchronised-content"
        self.page.test_synchronized_urlfield = "https://test.synchronised/content"
        self.page.test_synchronized_richtextfield = "<p>Test synchronised content</p>"
        # self.page.test_synchronized_streamfield = ""
        synchronized_snippet = TestSnippet.objects.create(field="Synchronised snippet")
        self.page.test_synchronized_snippet = synchronized_snippet
        self.page.test_synchronized_customfield = "Test synchronised content"

        # Add some child objects
        self.page.test_childobjects.add(TestChildObject(field="A test child object"))

        # Remove one of the child objects to test that deletions are syncrhonised
        self.page.test_synchronized_childobjects.remove(
            self.page.test_synchronized_childobjects.get(
                field="Test child object that existed before initial translation and was deleted"
            )
        )
        self.page.test_synchronized_childobjects.add(
            TestSynchronizedChildObject(field="A test synchronized object")
        )

        # Non-parental child objects are created differently because modelcluster doesn't help us
        TestNonParentalChildObject.objects.create(
            page=self.page, field="A non-parental child object"
        )

        # Save the page
        revision = self.page.save_revision()
        revision.publish()
        self.page.refresh_from_db()
        (
            source_with_changed_content,
            created,
        ) = TranslationSource.update_or_create_from_instance(self.page)

        # Check translation hasn't been updated yet
        translated.refresh_from_db()
        self.assertEqual(translated.test_synchronized_charfield, "")

        # Update the original page again. This will make sure it's taking the content from the translation source and not the live version
        self.page.test_synchronized_charfield = (
            "Test synchronised content updated again"
        )
        self.page.save_revision().publish()

        (
            new_page,
            created,
        ) = source_with_changed_content.create_or_update_translation(
            self.dest_locale,
            fallback=True,
        )

        self.assertFalse(created)
        self.assertEqual(new_page, translated)
        self.assertEqual(
            new_page.test_synchronized_charfield, "Test synchronised content"
        )
        self.assertEqual(
            new_page.test_synchronized_charfield, "Test synchronised content"
        )
        self.assertEqual(
            new_page.test_synchronized_textfield, "Test synchronised content"
        )
        self.assertEqual(
            new_page.test_synchronized_emailfield, "test@synchronised.content"
        )
        self.assertEqual(
            new_page.test_synchronized_slugfield, "test-synchronised-content"
        )
        self.assertEqual(
            new_page.test_synchronized_urlfield, "https://test.synchronised/content"
        )
        self.assertEqual(
            new_page.test_synchronized_richtextfield, "<p>Test synchronised content</p>"
        )
        self.assertEqual(new_page.test_synchronized_snippet, synchronized_snippet)
        self.assertEqual(
            new_page.test_synchronized_customfield, "Test synchronised content"
        )

        # Translatable child objects should always be synchronised
        # Locale should be updated but translation key should be the same
        translatable_child_object = new_page.test_childobjects.get()
        self.assertEqual(translatable_child_object.field, "A test child object")
        self.assertEqual(translatable_child_object.locale, self.dest_locale)
        self.assertTrue(translatable_child_object.has_translation(self.source_locale))

        # Test both the non deleted and new synchronised child objects remain
        self.assertEqual(
            set(
                new_page.test_synchronized_childobjects.values_list("field", flat=True)
            ),
            {
                "A test synchronized object",
                "Test child object that existed before initial translation and was not deleted",
            },
        )

        # Non parental child objects should be ignored
        self.assertFalse(new_page.test_nonparentalchildobjects.exists())

    def test_update_streamfields(self):
        # Streamfields are special in that they contain content that needs to be synchronised as well as
        # translatable content.

        # Copy page for translation, this will have a blank streamfield
        translated = self.page.copy_for_translation(self.dest_locale)

        # Set streamfield value on original
        self.page.test_streamfield = StreamValue(
            TestPage.test_streamfield.field.stream_block,
            [
                {
                    "id": "id",
                    "type": "test_charblock",
                    "value": "This is some test content",
                }
            ],
            is_lazy=True,
        )

        # Save the page
        revision = self.page.save_revision()
        revision.publish()
        self.page.refresh_from_db()
        (
            source_with_streamfield,
            created,
        ) = TranslationSource.update_or_create_from_instance(self.page)

        # Create a translation for the new context
        StringTranslation.objects.create(
            translation_of=self.string,
            locale=self.dest_locale,
            context=TranslationContext.objects.get(
                object_id=self.page.translation_key, path="test_streamfield.id"
            ),
            data="Ceci est du contenu de test",
        )

        new_page, created = source_with_streamfield.create_or_update_translation(
            self.dest_locale
        )

        self.assertFalse(created)
        self.assertEqual(new_page, translated)

        # Check the block was copied into translation
        self.assertEqual(new_page.test_streamfield[0].id, "id")
        self.assertEqual(
            new_page.test_streamfield[0].value, "Ceci est du contenu de test"
        )

    def test_create_translations_not_ready(self):
        self.translation.delete()

        with self.assertRaises(MissingTranslationError) as e:
            self.source.create_or_update_translation(self.dest_locale)

        self.assertEqual(e.exception.segment.source, self.source)
        self.assertEqual(e.exception.segment.context.path, "test_charfield")
        self.assertEqual(e.exception.segment.string, self.string)
        self.assertEqual(e.exception.locale, self.dest_locale)

    @override_settings(WAGTAILLOCALIZE_DISABLE_ON_DELETE=True)
    def test_create_related_object_not_ready(self):
        self.translated_snippet.delete()

        with self.assertRaises(MissingRelatedObjectError) as e:
            self.source.create_or_update_translation(self.dest_locale)

        self.assertEqual(e.exception.segment.source, self.source)
        self.assertEqual(e.exception.segment.context.path, "test_snippet")
        self.assertEqual(e.exception.segment.object_id, self.snippet.translation_key)
        self.assertEqual(e.exception.locale, self.dest_locale)

    def test_create_not_ready_with_fallback_true(self):
        # Same as previous two tests, except we pass `fallback=True` this time
        # so it falls back to the source value instead of raising an exception.
        self.translation.delete()
        self.translated_snippet.delete()

        translated_page, created = self.source.create_or_update_translation(
            self.dest_locale, fallback=True
        )

        self.assertEqual(translated_page.test_snippet, self.snippet)
        self.assertEqual(translated_page.test_charfield, "This is some test content")

    def test_create_with_fallback_true(self):
        # Like the previous test, but this time we have valid data, so it shouldn't fallback
        translated_page, created = self.source.create_or_update_translation(
            self.dest_locale, fallback=True
        )

        self.assertEqual(translated_page.test_snippet, self.translated_snippet)
        self.assertEqual(translated_page.test_charfield, "Ceci est du contenu de test")

    def test_convert_alias(self):
        self.page.copy_for_translation(self.dest_locale, alias=True)

        new_page, created = self.source.create_or_update_translation(self.dest_locale)

        self.assertFalse(created)
        self.assertIsNone(new_page.alias_of)
        self.assertEqual(new_page.title, "Test page")
        self.assertEqual(new_page.slug, "test-page-fr")
        self.assertEqual(new_page.test_charfield, "Ceci est du contenu de test")
        self.assertEqual(new_page.translation_key, self.page.translation_key)
        self.assertEqual(new_page.locale, self.dest_locale)
        self.assertTrue(
            self.source.translation_logs.filter(locale=self.dest_locale).exists()
        )

        # Check a log was created for the alias conversion
        self.assertTrue(
            PageLogEntry.objects.filter(
                page=new_page, action="wagtail.convert_alias"
            ).exists()
        )


class TestCreateOrUpdateTranslationForSnippet(TestCase):
    def setUp(self):
        self.snippet = TestSnippet.objects.create(
            field="Test snippet content", small_charfield="Small text"
        )
        self.source, created = TranslationSource.get_or_create_from_instance(
            self.snippet
        )
        self.source_locale = Locale.objects.get(language_code="en")
        self.dest_locale = Locale.objects.create(language_code="fr")

        # Add translation for field
        self.string = String.from_value(
            self.source_locale, StringValue.from_plaintext("Test snippet content")
        )
        self.translation = StringTranslation.objects.create(
            translation_of=self.string,
            locale=self.dest_locale,
            context=TranslationContext.objects.get(
                object_id=self.snippet.translation_key, path="field"
            ),
            data="Tester le contenu de l'extrait",
        )

        # Add translation for small_charfield
        self.small_string = String.from_value(
            self.source_locale, StringValue.from_plaintext("Small text")
        )
        self.small_translation = StringTranslation.objects.create(
            translation_of=self.small_string,
            locale=self.dest_locale,
            context=TranslationContext.objects.get(
                object_id=self.snippet.translation_key, path="small_charfield"
            ),
            data="Petit text",  # Truncated to fit because the field is limited to 10 characters
        )

    def test_create(self):
        new_snippet, created = self.source.create_or_update_translation(
            self.dest_locale
        )

        self.assertTrue(created)
        self.assertEqual(new_snippet.field, "Tester le contenu de l'extrait")
        self.assertEqual(new_snippet.translation_key, self.snippet.translation_key)
        self.assertEqual(new_snippet.locale, self.dest_locale)
        self.assertTrue(
            self.source.translation_logs.filter(locale=self.dest_locale).exists()
        )

    def test_create_validates_fields(self):
        self.small_translation.data = "Petit texte"  # More than 10 characters
        self.small_translation.save()

        with self.assertRaises(ValidationError) as e:
            self.source.create_or_update_translation(self.dest_locale)

        self.assertEqual(
            e.exception.messages,
            ["Ensure this value has at most 10 characters (it has 11)."],
        )

    def test_update(self):
        self.snippet.copy_for_translation(self.dest_locale).save()

        new_snippet, created = self.source.create_or_update_translation(
            self.dest_locale
        )

        self.assertFalse(created)
        self.assertEqual(new_snippet.field, "Tester le contenu de l'extrait")
        self.assertEqual(new_snippet.translation_key, self.snippet.translation_key)
        self.assertEqual(new_snippet.locale, self.dest_locale)
        self.assertTrue(
            self.source.translation_logs.filter(locale=self.dest_locale).exists()
        )

    def test_update_validates_fields(self):
        self.snippet.copy_for_translation(self.dest_locale).save()

        self.small_translation.data = "Petit texte"  # More than 10 characters
        self.small_translation.save()

        with self.assertRaises(ValidationError) as e:
            self.source.create_or_update_translation(self.dest_locale)

        self.assertEqual(
            e.exception.messages,
            ["Ensure this value has at most 10 characters (it has 11)."],
        )


class TestCreateOrUpdateTranslationForRevisionsWithoutDraftsSnippet(
    TransactionTestCase
):
    def setUp(self):
        # The default locale created by Wagtail gets flushed when using TransactionTestCase
        # however this is necessary to check the behaviour of on_commit hook in
        # the update_or_create_translation method
        self.source_locale, _ = Locale.objects.get_or_create(language_code="en")
        self.dest_locale = Locale.objects.create(language_code="fr")

        self.snippet = TestRevisionsButNoDraftModel.objects.create(
            field="Test snippet content"
        )
        self.source, created = TranslationSource.get_or_create_from_instance(
            self.snippet
        )

        # Add translation for field
        self.string = String.from_value(
            self.source_locale, StringValue.from_plaintext("Test snippet content")
        )
        self.translation = StringTranslation.objects.create(
            translation_of=self.string,
            locale=self.dest_locale,
            context=TranslationContext.objects.get(
                object_id=self.snippet.translation_key, path="field"
            ),
            data="Tester le contenu",
        )

    def test_create(self):
        new_snippet, created = self.source.create_or_update_translation(
            self.dest_locale
        )

        self.assertTrue(created)
        self.assertEqual(new_snippet.field, "Tester le contenu")
        self.assertEqual(new_snippet.translation_key, self.snippet.translation_key)
        self.assertEqual(new_snippet.locale, self.dest_locale)
        self.assertTrue(
            self.source.translation_logs.filter(locale=self.dest_locale).exists()
        )

    def test_update(self):
        self.snippet.copy_for_translation(self.dest_locale).save()

        new_snippet, created = self.source.create_or_update_translation(
            self.dest_locale
        )

        self.assertFalse(created)
        self.assertEqual(new_snippet.field, "Tester le contenu")
        self.assertEqual(new_snippet.translation_key, self.snippet.translation_key)
        self.assertEqual(new_snippet.locale, self.dest_locale)
        self.assertTrue(
            self.source.translation_logs.filter(locale=self.dest_locale).exists()
        )


class TestGetEphemeralTranslatedInstance(TestCase):
    def setUp(self):
        self.page = create_test_page(
            title="Test page",
            slug="test-page",
            test_charfield="This is some test content",
            test_textfield="This is some more test content",
        )
        self.source, created = TranslationSource.get_or_create_from_instance(self.page)
        self.source_locale = Locale.objects.get(language_code="en")
        self.dest_locale = Locale.objects.create(language_code="fr")

        # Translate the page
        self.translated_page = self.page.copy_for_translation(self.dest_locale)

        # Add a test child object and update the test_textfield. Then update the translation source
        self.page.test_childobjects.add(
            TestChildObject(field="This is a test child object")
        )
        self.page.test_textfield = "Updated textfield"
        self.page.save_revision().publish()
        self.source.update_from_db()

        # Add translation for test_charfield
        self.translation = StringTranslation.objects.create(
            translation_of=String.objects.get(data="This is some test content"),
            locale=self.dest_locale,
            context=TranslationContext.objects.get(
                object_id=self.page.translation_key, path="test_charfield"
            ),
            data="Ceci est du contenu de test",
        )

        # Add translation for child object
        self.translation = StringTranslation.objects.create(
            translation_of=String.objects.get(data="This is a test child object"),
            locale=self.dest_locale,
            context=TranslationContext.objects.get(
                object_id=self.page.translation_key,
                path=f"test_childobjects.{self.page.test_childobjects.get().translation_key}.field",
            ),
            data="Ceci est un objet enfant de test",
        )

    def test_get_ephemeral_translated_instance(self):
        new_page = self.source.get_ephemeral_translated_instance(
            self.dest_locale, fallback=True
        )

        self.assertEqual(new_page.id, self.translated_page.id)
        self.assertEqual(new_page.test_charfield, "Ceci est du contenu de test")
        self.assertEqual(new_page.test_textfield, "Updated textfield")
        self.assertEqual(
            new_page.test_childobjects.get().field, "Ceci est un objet enfant de test"
        )
        self.assertFalse(
            self.source.translation_logs.filter(locale=self.dest_locale).exists()
        )

        # Check the saved page has not been changed
        self.translated_page.refresh_from_db()
        self.assertEqual(self.translated_page.title, "Test page")
        self.assertEqual(
            self.translated_page.test_charfield, "This is some test content"
        )
        self.assertEqual(
            self.translated_page.test_textfield, "This is some more test content"
        )
        self.assertFalse(self.translated_page.test_childobjects.exists())

    def test_without_fallback(self):
        # Should raise an error because we haven't translated test_textfield
        with self.assertRaises(MissingTranslationError):
            self.source.get_ephemeral_translated_instance(self.dest_locale)

        # Add a translation for test_textfield to make the error go away
        self.translation = StringTranslation.objects.create(
            translation_of=String.objects.get(data="Updated textfield"),
            locale=self.dest_locale,
            context=TranslationContext.objects.get(
                object_id=self.page.translation_key, path="test_textfield"
            ),
            data="Champ de texte mis à jour",
        )

        new_page = self.source.get_ephemeral_translated_instance(self.dest_locale)
        self.assertEqual(new_page.test_textfield, "Champ de texte mis à jour")


class TestSchemaOutOfDate(TestCase):
    def setUp(self):
        self.page = create_test_page(
            title="Test page",
            slug="test-page",
            test_charfield="This is some test content",
            test_textfield="This is some more test content",
        )
        self.source, created = TranslationSource.get_or_create_from_instance(self.page)

    def test_schema_is_in_date_for_new_instance(self):
        self.assertTrue(self.source.schema_version)
        self.assertFalse(self.source.schema_out_of_date())

    def test_schema_is_in_date_if_source_schema_version_is_unknown(self):
        self.source.schema_version = ""
        self.source.save()
        self.assertFalse(self.source.schema_out_of_date())

    def test_schema_is_out_of_date_if_source_schema_version_is_old(self):
        # note: we reset test app migrations on a regular basis, so
        # this sets a stub initial schema version.
        self.source.schema_version = "0001_initial_stub"
        self.source.save()
        self.assertTrue(self.source.schema_out_of_date())


SEGMENT_MODELS = (
    StringSegment,
    TemplateSegment,
    RelatedObjectSegment,
    OverridableSegment,
)


def refresh_page(**kwargs):
    """A page carrying all four kinds of segment, plus its reconciled source."""
    snippet = TestSnippet.objects.create(field=kwargs.pop("snippet_field", "A snippet"))
    blocks = kwargs.pop("blocks", ["Block 0", "Block 1"])
    page = create_test_page(
        test_charfield="Some translatable content",
        test_richtextfield="<p>Some <b>rich</b> text</p>",
        test_snippet=snippet,
        test_synchronized_charfield="Overridable content",
        test_streamfield=StreamValue(
            TestStreamBlock(),
            [{"type": "test_charblock", "value": block} for block in blocks],
            is_lazy=True,
        ),
        **kwargs,
    )
    return page, TranslationSource.objects.get(object_id=page.translation_key)


def segment_rows(source):
    """Every segment row of every type, as (pk, context, order) in pk order."""
    return {
        model.__name__: [
            (segment.pk, segment.context_id, segment.order)
            for segment in model.objects.filter(source=source).order_by("pk")
        ]
        for model in SEGMENT_MODELS
    }


class TestValueCandidates(TestCase):
    def test_string_candidate_matches_from_value_for_locale_or_id(self):
        locale = Locale.get_default()

        for locale_arg, data in (
            (locale, "Built from a locale"),
            (locale.pk, "Built from a locale id"),
        ):
            with self.subTest(locale_arg=locale_arg):
                value = StringValue(data)
                with self.assertNumQueries(0):
                    candidate = String._candidate_from_value(locale_arg, value)

                stored = String.from_value(locale_arg, value)
                existing = String.from_value(locale_arg, value)

                self.assertIsNone(candidate.pk)
                self.assertEqual(candidate.locale_id, stored.locale_id)
                self.assertEqual(candidate.data_hash, stored.data_hash)
                self.assertEqual(candidate.data, stored.data)
                self.assertEqual(existing.pk, stored.pk)

    def test_template_candidate_matches_from_value(self):
        value = TemplateSegmentValue(
            "test_richtextfield",
            "html",
            "<p>Template candidate</p>",
            1,
            order=0,
        )

        with self.assertNumQueries(0):
            candidate = Template._candidate_from_value(value)

        stored = Template.from_value(value)
        existing = Template.from_value(value)

        self.assertIsNone(candidate.pk)
        self.assertEqual(candidate.uuid, stored.uuid)
        self.assertEqual(candidate.template, stored.template)
        self.assertEqual(candidate.template_format, stored.template_format)
        self.assertEqual(candidate.string_count, stored.string_count)
        self.assertEqual(existing.pk, stored.pk)

    def test_context_candidate_matches_the_stored_context(self):
        _page, source = refresh_page(
            title="Context candidate", slug="context-candidate"
        )
        stored = TranslationContext.objects.get(
            object_id=source.object_id, path="test_charfield"
        )

        with self.assertNumQueries(0):
            candidate = TranslationContext._candidate_from_path(
                source.object_id, stored.path
            )

        self.assertIsNone(candidate.pk)
        self.assertEqual(candidate.object_id, stored.object_id)
        self.assertEqual(candidate.path, stored.path)
        self.assertEqual(candidate.path_id, stored.path_id)


class TestRefreshSegmentsBehaviour(TestCase):
    def test_refreshing_an_unchanged_source_changes_nothing(self):
        _page, source = refresh_page(title="Warm", slug="warm")
        before = segment_rows(source)

        with mock.patch(
            "wagtail_localize.models._compute_field_path"
        ) as compute_field_path:
            source.refresh_segments()

        # Every context already has its field path, so nothing has to walk the
        # instance to work one out.
        compute_field_path.assert_not_called()
        self.assertEqual(segment_rows(source), before)
        for model in SEGMENT_MODELS:
            with self.subTest(model=model.__name__):
                self.assertTrue(before[model.__name__])

    def test_changed_content_adds_and_removes_only_what_moved(self):
        page, source = refresh_page(
            title="Changed", slug="changed", blocks=["Keep me", "Also keep me"]
        )
        # The stream blocks are left alone, so their rows should be too. Only
        # the charfield's segment has anything to change about it.
        untouched = {
            data: StringSegment.objects.get(source=source, string__data=data).pk
            for data in ("Keep me", "Also keep me")
        }

        page.test_charfield = "Brand new content"
        page.save_revision().publish()
        source.update_from_db()

        data = set(
            StringSegment.objects.filter(source=source).values_list(
                "string__data", flat=True
            )
        )
        self.assertIn("Brand new content", data)
        self.assertNotIn("Some translatable content", data)
        for value, pk in untouched.items():
            with self.subTest(segment=value):
                self.assertEqual(
                    StringSegment.objects.get(source=source, string__data=value).pk, pk
                )

    def test_a_first_extraction_writes_every_type_and_keeps_it(self):
        snippet = TestSnippet.objects.create(field="First snippet")
        page = Page.objects.get(id=1).add_child(
            instance=TestPage(
                title="First",
                slug="first",
                test_charfield="Some translatable content",
                test_richtextfield="<p>Some <b>rich</b> text</p>",
                test_snippet=snippet,
                test_synchronized_charfield="Overridable content",
                test_streamfield=StreamValue(
                    TestStreamBlock(),
                    [{"type": "test_charblock", "value": "Block 0"}],
                    is_lazy=True,
                ),
            )
        )
        page.save_revision().publish()
        page.refresh_from_db()

        source, created = TranslationSource.get_or_create_from_instance(page)
        self.assertTrue(created)

        # Read the tables again: an insert that the reconciliation deleted
        # would be invisible in the objects the call returned.
        for model in SEGMENT_MODELS:
            with self.subTest(model=model.__name__):
                self.assertTrue(model.objects.filter(source=source).exists())
        self.assertEqual(
            set(
                StringSegment.objects.filter(source=source).values_list(
                    "string__data", flat=True
                )
            ),
            {"Some translatable content", "Some <b>rich</b> text", "Block 0"},
        )

    def test_a_repeated_string_is_stored_once(self):
        _page, source = refresh_page(
            title="Repeats", slug="repeats", blocks=["Same text", "Same text"]
        )

        self.assertEqual(String.objects.filter(data="Same text").count(), 1)
        self.assertEqual(
            StringSegment.objects.filter(
                source=source, string__data="Same text"
            ).count(),
            2,
        )

    def test_derived_fields_are_computed_for_rows_it_creates(self):
        _page, source = refresh_page(title="Derived", slug="derived")

        for string in String.objects.filter(segments__source=source).distinct():
            with self.subTest(data=string.data):
                self.assertEqual(string.data_hash, String._get_data_hash(string.data))

        contexts = TranslationContext.objects.filter(object_id=source.object_id)
        self.assertTrue(contexts.exists())
        for context in contexts:
            with self.subTest(path=context.path):
                self.assertEqual(
                    context.path_id, TranslationContext._get_path_id(context.path)
                )
                self.assertTrue(context.field_path)

        template = TemplateSegment.objects.get(source=source).template
        namespace = uuid.uuid5(Template.BASE_UUID_NAMESPACE, template.template_format)
        self.assertEqual(template.uuid, uuid.uuid5(namespace, template.template))

    def test_a_duplicated_row_for_a_wanted_key_is_not_hidden(self):
        _page, source = refresh_page(title="Duplicated", slug="duplicated")
        original = StringSegment.objects.get(source=source, string__data="Block 0")
        StringSegment.objects.create(
            source=source,
            context=original.context,
            order=original.order,
            string=original.string,
            attrs=original.attrs,
        )

        # The get_or_create() this replaced raised for the same reason.
        with self.assertRaises(StringSegment.MultipleObjectsReturned):
            source.refresh_segments()

        self.assertEqual(
            StringSegment.objects.filter(source=source, string__data="Block 0").count(),
            2,
        )


class TestRefreshSegmentsStaleRows(TestCase):
    """Split out because it drives the page through a content change after
    leaving duplicated rows behind."""

    def test_duplicates_of_a_key_that_is_gone_are_deleted(self):
        page, source = refresh_page(
            title="Stale", slug="stale", blocks=["Going away", "Staying"]
        )
        original = StringSegment.objects.get(source=source, string__data="Going away")
        StringSegment.objects.create(
            source=source,
            context=original.context,
            order=original.order,
            string=original.string,
            attrs=original.attrs,
        )

        page.test_streamfield = StreamValue(
            TestStreamBlock(),
            [{"type": "test_charblock", "value": "Staying"}],
            is_lazy=True,
        )
        page.save_revision().publish()
        source.update_from_db()

        self.assertFalse(
            StringSegment.objects.filter(
                source=source, string__data="Going away"
            ).exists()
        )
        self.assertTrue(
            StringSegment.objects.filter(source=source, string__data="Staying").exists()
        )


class TestRefreshSegmentsQueryCount(TestCase):
    def _count_refresh_queries(self, num_blocks):
        page = create_test_page(
            title=f"Test page {num_blocks}",
            slug=f"test-page-{num_blocks}",
            test_charfield="Some translatable content",
            test_textfield="Some more translatable content",
            test_streamfield=StreamValue(
                TestStreamBlock(),
                [
                    {"type": "test_charblock", "value": f"Block {i}"}
                    for i in range(num_blocks)
                ],
                is_lazy=True,
            ),
        )
        source = TranslationSource.objects.get(object_id=page.translation_key)

        with CaptureQueriesContext(connection) as ctx:
            source.refresh_segments()

        return len(ctx.captured_queries)

    def test_refresh_segments_query_count_does_not_grow_with_segments(self):
        # Equality between two sizes rather than an absolute number: what the
        # optimisation promises is that reconciling a source costs the same
        # whether it holds three segments or twelve.
        small = self._count_refresh_queries(num_blocks=3)
        large = self._count_refresh_queries(num_blocks=12)

        self.assertEqual(small, large)

    def test_refresh_does_not_load_the_source_locale_relation(self):
        page = create_test_page(title="Deferred locale", slug="deferred-locale")
        source = TranslationSource.objects.get(object_id=page.translation_key)
        self.assertNotIn("locale", source._state.fields_cache)

        source.refresh_segments()

        self.assertNotIn("locale", source._state.fields_cache)


class TestRefreshSegmentsIdentity(TestCase):
    """Two values that differ only in the part of a natural key the lookup
    covers must not resolve to the same row."""

    def setUp(self):
        self.page, self.source = refresh_page(title="Identity", slug="identity")

    def refresh_with(self, values):
        with mock.patch(
            "wagtail_localize.models.extract_segments", return_value=values
        ):
            self.source.refresh_segments()

    def test_the_same_markup_in_two_formats_is_two_templates(self):
        markup = "<p>Same markup, two formats</p>"
        self.refresh_with(
            [
                TemplateSegmentValue("test_richtextfield", "html", markup, 0, order=0),
                TemplateSegmentValue(
                    "test_synchronized_richtextfield", "text", markup, 0, order=1
                ),
            ]
        )

        templates = Template.objects.filter(template=markup)
        self.assertEqual(templates.count(), 2)
        self.assertEqual(
            {template.template_format for template in templates}, {"html", "text"}
        )
        self.assertEqual(len({template.uuid for template in templates}), 2)
        self.assertEqual(TemplateSegment.objects.filter(source=self.source).count(), 2)

    def test_a_string_hash_collision_is_not_resolved_to_the_wrong_string(self):
        existing = String.from_value(
            self.source.locale_id, StringValue("Existing string")
        )
        colliding = StringSegmentValue("test_charfield", "Different string")

        with (
            mock.patch.object(
                String, "_get_data_hash", return_value=existing.data_hash
            ),
            self.assertRaisesRegex(
                IntegrityError, "could not resolve String for 'Different string'"
            ),
        ):
            self.source._strings_for_values([colliding])

        self.assertFalse(String.objects.filter(data="Different string").exists())

    def test_one_translation_key_under_two_content_types_is_refused(self):
        translation_key = TestSnippet.objects.first().translation_key
        page_type = ContentType.objects.get_for_model(Page)
        snippet_type = ContentType.objects.get_for_model(TestSnippet)

        # The stored object is the snippet, and it comes second on purpose: an
        # index keyed on translation_key alone would resolve the whole key from
        # this value and hand the page-typed value the snippet's object without
        # noticing.
        with self.assertRaises(IntegrityError):
            self.refresh_with(
                [
                    RelatedObjectSegmentValue(
                        "test_page", page_type, translation_key, order=0
                    ),
                    RelatedObjectSegmentValue(
                        "test_snippet", snippet_type, translation_key, order=1
                    ),
                ]
            )

        # Nothing was attached to the object of the wrong type.
        self.assertFalse(
            RelatedObjectSegment.objects.filter(object__content_type=page_type).exists()
        )
