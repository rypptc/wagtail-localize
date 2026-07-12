"""
Django bootstrap shared by every script in benchmarks/. Call bootstrap()
before importing anything that needs Django configured (models, settings).

Idempotent — django.setup() is a no-op if apps are already configured, so
it's safe to call from more than one file. That matters here: relying on
one script's *import* to trigger another's bootstrap as a side effect broke
the first time an automatic import-sorter reordered things alphabetically
("cases" before "seed"). A bootstrap() call sits between import blocks, and
isort won't reorder an import across a function call — so this is immune to
that class of breakage.
"""

import os
import sys


def bootstrap():
    # Make the repo root importable, so `tests.testapp...` resolves. This
    # file is benchmarks/env.py, so one level up is the repo root.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.testapp.settings")
    os.environ.setdefault("DATABASE_URL", "sqlite:///benchmark.db")

    import django

    django.setup()
