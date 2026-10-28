"""Command-line interface for the job vacancy bot."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import __version__
from .config import DEFAULT_CONFIG_PATH, load_config
from .http_client import FetchError
from .pipeline import JobBot, RunResult
from .portals import PORTALS, BusinessError

LOGGER = logging.getLogger("rpa.jobs")

BANNER = """
╔════════════════════════════════════════════════════════════════════╗
║  RPA JOB VACANCY BOT  ·  web automation -> Excel report            ║
╚════════════════════════════════════════════════════════════════════╝
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_bot.py",
        description="Collect job vacancies from a portal and write an Excel report.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python run_bot.py                              # 50 live jobs from all sources\n"
            "  python run_bot.py --keyword python            # India-only, Python roles\n"
            "  python run_bot.py --country india --keyword django\n"
            "  python run_bot.py --country none              # worldwide (no location filter)\n"
            "  python run_bot.py --portal python-jobs --limit 10 --no-details\n"
            "  python run_bot.py --append --output output/weekly_jobs.xlsx\n"
        ),
    )
    parser.add_argument("--portal", choices=sorted(PORTALS), help="job portal adapter to use")
    parser.add_argument("--limit", type=int, help="maximum number of vacancies to collect")
    parser.add_argument(
        "--country",
        action="append",
        metavar="NAME",
        help="only keep vacancies in this country (repeatable; 'none' clears the filter)",
    )
    parser.add_argument(
        "--keyword",
        action="append",
        metavar="WORD",
        help="only keep vacancies matching this word (repeatable, comma-separated allowed)",
    )
    parser.add_argument(
        "--match",
        choices=("any", "all"),
        help="with --keyword: require any keyword (default) or all of them",
    )
    parser.add_argument("--output", help="path of the .xlsx report to write")
    parser.add_argument("--config", default=None, help="path to a JSON config file")
    parser.add_argument(
        "--no-details",
        action="store_true",
        help="skip per-job detail pages (faster, fewer fields)",
    )
    parser.add_argument("--delay", type=float, help="seconds to wait between requests per host")
    parser.add_argument(
        "--append",
        action="store_true",
        help="merge into an existing report and skip vacancies already recorded",
    )
    parser.add_argument("--list-portals", action="store_true", help="show available adapters and exit")
    parser.add_argument("--verbose", "-v", action="store_true", help="enable debug logging")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def configure_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s", "%H:%M:%S"))
    logger = logging.getLogger("rpa.jobs")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False


def apply_overrides(config: dict, args: argparse.Namespace) -> dict:
    if args.portal:
        config["portal"] = args.portal
    if args.limit is not None:
        if args.limit < 1:
            raise BusinessError("--limit must be at least 1")
        config.setdefault("crawl", {})["max_items"] = args.limit
    if args.no_details:
        config.setdefault("crawl", {})["fetch_details"] = False
    if args.delay is not None:
        if args.delay < 0:
            raise BusinessError("--delay cannot be negative")
        config.setdefault("crawl", {})["delay_seconds"] = args.delay
    if args.output:
        config["_output_override"] = str(Path(args.output).expanduser().resolve())
    if args.keyword:
        keywords: list[str] = []
        for raw in args.keyword:
            keywords.extend(part.strip() for part in raw.split(",") if part.strip())
        if keywords:
            config.setdefault("filters", {})["keywords"] = keywords
    if args.country:
        countries: list[str] = []
        for raw in args.country:
            countries.extend(part.strip() for part in raw.split(",") if part.strip())
        if any(value.lower() in {"none", "any", "all", "worldwide"} for value in countries):
            countries = []
        config.setdefault("filters", {})["countries"] = countries
    if args.match:
        config.setdefault("filters", {})["match"] = args.match
    return config


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_portals:
        for name, portal_cls in sorted(PORTALS.items()):
            print(f"  {name:<14} {portal_cls.label}")
        return 0

    configure_logging(args.verbose)

    try:
        config = load_config(args.config)
        config = apply_overrides(config, args)

        if args.config is None:
            LOGGER.debug("Using default config %s", DEFAULT_CONFIG_PATH)

        print(BANNER)
        LOGGER.info(
            "Robot starting | portal=%s | limit=%s | details=%s",
            config["portal"],
            config["crawl"].get("max_items"),
            "on" if config["crawl"].get("fetch_details", True) else "off",
        )

        bot = JobBot(
            config,
            append=args.append,
            output=config.get("_output_override"),
        )
        result = bot.run()
        print_summary(result)
        return 0

    except KeyboardInterrupt:
        LOGGER.warning("Interrupted by user - no report written")
        return 130
    except (BusinessError, FetchError) as exc:
        LOGGER.error("%s", exc)
        return 1
    except Exception as exc:  # noqa: BLE001 - top-level guard
        LOGGER.error("Unexpected failure: %s", exc, exc_info=args.verbose)
        return 2


# --------------------------------------------------------------------------- output
def print_summary(result: RunResult) -> None:
    line = "─" * 68
    print()
    print(line)
    print(" RUN COMPLETE")
    print(line)
    print(f"  Portal              : {result.portal_label}")
    print(f"  Vacancies discovered: {result.discovered}")
    print(f"  New rows written    : {result.successful}")
    print(f"  Duplicates skipped  : {result.skipped}")
    if result.filtered_location:
        print(f"  Outside location    : {result.filtered_location}")
    if result.filtered:
        print(f"  Filtered out        : {result.filtered}")
    print(f"  Failed transactions : {result.failed}")
    if result.carried_over:
        print(f"  Existing rows kept  : {result.carried_over}")
    print(f"  Total rows in report: {len(result.jobs)}")
    print(f"  Duration            : {result.duration_seconds:.1f}s")
    print(f"  Excel report        : {result.output_path}")

    if result.jobs:
        print()
        _print_preview(result)
    print(line)


def _print_preview(result: RunResult, rows: int = 5) -> None:
    print(f" Preview (first {min(rows, len(result.jobs))} of {len(result.jobs)} vacancies)")
    print(f"  {'JOB TITLE':<40} {'COMPANY':<26} {'LOCATION':<20} {'MODE':<10}")
    print(f"  {'-' * 39} {'-' * 25} {'-' * 19} {'-' * 9}")
    for job in result.jobs[:rows]:
        print(
            f"  {_cut(job.title, 40):<40} {_cut(job.company, 26):<26} "
            f"{_cut(job.location, 20):<20} {job.work_mode:<10}"
        )
    if len(result.jobs) > rows:
        print(f"  ... {len(result.jobs) - rows} more rows in the workbook")


def _cut(value: str, width: int) -> str:
    text = value or ""
    return text if len(text) <= width else text[: width - 1] + "…"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
