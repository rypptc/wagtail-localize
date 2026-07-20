"""
django-query-doctor evaluation runner. flows.py owns the catalog (WHAT we
evaluate); this file owns only HOW Query Doctor measures it. --list stays
cheap — no Django, DB, or query_doctor — because it just prints the shared
catalog.

    DATABASE_URL=sqlite:///benchmark.db .venv-query-doctor/bin/python benchmarks/run_query_doctor.py --list
    DATABASE_URL=sqlite:///benchmark.db .venv-query-doctor/bin/python benchmarks/run_query_doctor.py --migrate submit_page_post
    DATABASE_URL=sqlite:///benchmark.db .venv-query-doctor/bin/python benchmarks/run_query_doctor.py all
"""

import argparse
import sys

import env

from flows import FLOW_CATALOG, FLOWS_BY_NAME, prepare, print_catalog


def diagnose(label, fn):
    """Run `fn` under Query Doctor and print what it found. The only place that
    imports query_doctor — so everything else stays tool-agnostic."""
    from query_doctor import diagnose_queries
    from query_doctor.reporters.console import ConsoleReporter

    print(f"\n=== {label} ===")
    with diagnose_queries() as report:
        result = fn()

    status = getattr(result, "status_code", None)
    if status is not None:
        print(f"status_code: {status}")
    print(f"total_queries: {report.total_queries}   issues: {report.issues}")
    print(ConsoleReporter().render(report))
    return result


def run_flow(flow):
    """Prepare fresh data and run any precondition (both unmeasured), then
    diagnose the flow action with Query Doctor."""
    ctx = prepare()
    if flow.setup is not None:
        flow.setup(ctx)
    diagnose(flow.name, lambda: flow.run(ctx))


def migrate():
    """Create the schema (and cache table) for the benchmark database."""
    from django.core.management import call_command
    from django.core.management.base import CommandError

    call_command("migrate", verbosity=0, interactive=False)
    try:
        call_command("createcachetable", "cache", verbosity=0)
    except CommandError as error:
        if "already exists" not in str(error):
            raise


def parse_args():
    parser = argparse.ArgumentParser(
        description="Evaluate django-query-doctor on wagtail-localize flows."
    )
    parser.add_argument(
        "flow",
        nargs="?",
        help="Flow name to run, or 'all'. Omit with --list. See --list for names.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print the flow catalog (why/entrypoint/covers/scale_dimensions) and exit.",
    )
    parser.add_argument(
        "--migrate",
        action="store_true",
        help="Run migrate + createcachetable before doing anything else.",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # --list alone is intentionally cheap: no Django, no DB, no Query Doctor.
    # Only bootstrap when we're going to migrate or run a flow.
    if args.list and not args.migrate:
        print_catalog()
        return 0

    env.bootstrap()

    if args.migrate:
        migrate()

    if args.list:
        print_catalog()
        return 0

    if not args.flow:
        print("Give a flow name or 'all' (or use --list).", file=sys.stderr)
        return 2

    if args.flow == "all":
        for flow in FLOW_CATALOG:
            run_flow(flow)
        return 0

    flow = FLOWS_BY_NAME.get(args.flow)
    if flow is None:
        names = ", ".join(FLOWS_BY_NAME)
        print(f"Unknown flow {args.flow!r}. Available: {names}", file=sys.stderr)
        return 2

    run_flow(flow)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
