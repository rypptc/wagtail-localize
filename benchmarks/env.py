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
    # This file is benchmarks/env.py, so one level up is the repo root. Make
    # both the repo root (so `tests.testapp...` resolves) and repo_root/src
    # (where the src/ layout puts `wagtail_localize`) importable — otherwise
    # `.venv/bin/python benchmarks/seed.py` fails with ModuleNotFoundError:
    # wagtail_localize when the package isn't installed editable.
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for path in (repo_root, os.path.join(repo_root, "src")):
        if path not in sys.path:
            sys.path.insert(0, path)

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.testapp.settings")
    os.environ.setdefault("DATABASE_URL", "sqlite:///benchmark.db")

    import django

    django.setup()
