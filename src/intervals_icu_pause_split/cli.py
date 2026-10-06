"""Split an intervals.icu activity into moving and pause intervals.

A pause is a stretch where you stood still (slower than --stop-speed) or the
device stopped recording, which is what auto-pause leaves behind: a jump in the
time stream. Stops with less than --merge of moving in between count as one
pause, and only pauses with at least --min-pause of standstill are kept.

Only the moving legs are written, as WORK intervals. intervals.icu fills the
gaps between them with RECOVERY intervals on its own; it does not accept
RECOVERY intervals (or labels on them) through the API.

Nothing is written without confirmation, and the intervals that get replaced
are backed up first.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Confirm

from . import __version__
from .client import Client
from .detect import STOP_SPEED, STOP_SPEED_ON_FOOT
from .errors import AuthError, NotFoundError, PauseSplitError
from .plan import Options, apply, plan, plan_restore
from .render import render_header, render_rule, render_summary, render_table, render_timeline
from .units import parse_activity_id, parse_duration, parse_edges

PROG = "intervals-icu-pause-split"

console = Console(highlight=False)

# Panels auf eine lesbare Breite begrenzen, statt sie das Terminal ausfuellen zu
# lassen. Schmale Terminals gewinnen weiterhin.
PANEL_WIDTH = 78


def panel(body: str, title: str, border_style: str) -> Panel:
    return Panel(body, title=title, border_style=border_style, width=min(PANEL_WIDTH, console.width))


def fail(message: str) -> None:
    console.print(panel(message, "Error", "red"))
    raise SystemExit(1)


def explain(exc: PauseSplitError) -> str:
    """The library's message, plus what to do about it on the command line."""
    if isinstance(exc, AuthError):
        return f"{exc}\nCheck the API key at https://intervals.icu/settings (bottom of the page)."
    if isinstance(exc, NotFoundError):
        return f"{exc}\nCheck the activity id, and that your API key can see it."
    return escape(str(exc))


# --- Backups ------------------------------------------------------------------


def backup_dir() -> Path:
    state = os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state"
    return Path(state) / PROG / "backups"


def save_backup(activity_id: str, previous: dict) -> Path:
    folder = backup_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{activity_id}-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps(previous, indent=2))
    return path


def read_backup(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        fail(f"Cannot read backup {escape(str(path))}: {escape(str(exc))}")


# --- Arguments ----------------------------------------------------------------


def arg_type(parse):
    """Let argparse show the parser's ValueError message instead of its generic one."""

    def convert(text: str):
        try:
            return parse(text)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(str(exc)) from None

    convert.__name__ = parse.__name__
    return convert


def build_parser() -> argparse.ArgumentParser:
    duration = arg_type(parse_duration)
    p = argparse.ArgumentParser(prog=PROG, description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("activity", help="Activity id (i87942121) or its URL (https://intervals.icu/activities/i87942121)")
    p.add_argument("--api-key", help="intervals.icu API key (env: INTERVALS_ICU_API_KEY)")
    p.add_argument(
        "--min-pause", type=duration, default=duration("5m"), metavar="DURATION",
        help="Minimum standstill for a pause, e.g. 90s, 5m, 1h; a bare number is minutes (default: 5m)",
    )
    p.add_argument(
        "--merge", type=duration, default=duration("60s"), metavar="DURATION",
        help="Stops with less moving than this in between count as one pause (default: 60s)",
    )
    p.add_argument(
        "--stop-speed", type=float, metavar="KMH",
        help=f"Below this speed you count as standing still, in km/h "
        f"(default: {STOP_SPEED_ON_FOOT:g} on foot, {STOP_SPEED:g} otherwise)",
    )
    p.add_argument(
        "--edges", type=arg_type(parse_edges), metavar="LENGTH[,LENGTH]",
        help="Split the first and last LENGTH of moving into Warmup and Cooldown intervals, e.g. for getting "
        "out of and back into town. A duration (10m) or a distance (3km); two values set them separately: "
        "--edges 3km,10m",
    )
    p.add_argument("--label", default="Leg", help="Label prefix for the moving intervals (default: Leg)")
    p.add_argument("--width", type=int, help="Width of the timeline (default: terminal width)")
    p.add_argument("--restore", type=Path, metavar="BACKUP", help="Put back the intervals from a backup file")
    p.add_argument("--dry-run", action="store_true", help="Show the preview, never write")
    p.add_argument("--yes", action="store_true", help="Write without asking")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def resolve_api_key(args: argparse.Namespace) -> str:
    load_dotenv()
    key = args.api_key or os.environ.get("INTERVALS_ICU_API_KEY")
    if not key:
        fail(
            "No API key.\n\n"
            "Pass --api-key, set INTERVALS_ICU_API_KEY, or put it in a .env file.\n"
            "You find the key at the bottom of https://intervals.icu/settings"
        )
    return key


# --- Main ---------------------------------------------------------------------


def main() -> None:
    try:
        run()
    except (KeyboardInterrupt, EOFError):
        # Ctrl-C anywhere before the write, or Ctrl-D at the prompt: nothing was sent.
        console.print("\n  Interrupted, nothing changed.\n")
        raise SystemExit(130) from None
    except PauseSplitError as exc:
        fail(explain(exc))


def run() -> None:
    args = build_parser().parse_args()
    if args.width:
        console.width = args.width
    client = Client(resolve_api_key(args))
    activity_id = parse_activity_id(args.activity)

    if args.restore:
        p = plan_restore(client, activity_id, read_backup(args.restore), stop_speed=args.stop_speed)
    else:
        warmup, cooldown = args.edges or (None, None)
        options = Options(
            min_pause=args.min_pause,
            merge=args.merge,
            stop_speed=args.stop_speed,
            warmup=warmup,
            cooldown=cooldown,
            label=args.label,
        )
        p = plan(client, activity_id, options)

    stop_speed = p.stop_speed / 3.6
    console.print()
    console.print(render_header(p))
    console.print(f"  [dim]{render_rule(p, args.restore)}[/]\n")
    for line in render_timeline(p.streams, [("Now", p.current), ("New", p.new)], p.start, console.width):
        console.print(line, no_wrap=True)
    console.print()
    if p.current:
        console.print(render_table(p.streams, p.current, p.start, stop_speed, "Now", short=True))
    else:
        console.print("[bold]Now[/]  [dim]no intervals[/]")
    console.print()
    console.print(render_table(p.streams, p.new, p.start, stop_speed, "New"))
    console.print(render_summary(p.streams, p.new))
    console.print()

    if not p.has_changes:
        console.print("  The activity already has these intervals, nothing to do.\n")
        return
    if args.dry_run:
        console.print("  [dim]--dry-run, nothing written.[/]\n")
        return
    if not args.yes:
        if not sys.stdin.isatty():
            console.print("  [yellow]Not a terminal; pass --yes to write unattended.[/]\n")
            return
        question = f"  Replace the {len(p.current)} intervals with these {len(p.new)}?"
        if not Confirm.ask(question, default=False):
            console.print("\n  Cancelled, nothing changed.\n")
            return

    backup = save_backup(activity_id, p.previous)
    undo = f"{PROG} {activity_id} --restore {escape(str(backup))}"
    try:
        result = apply(client, p)
    except KeyboardInterrupt:
        # The request may already have reached intervals.icu, so don't claim nothing changed.
        console.print(
            "\n  [yellow]Interrupted while writing; the intervals may or may not have changed.[/]\n"
            f"  [dim]Check the activity, or undo with: {undo}[/]\n"
        )
        raise SystemExit(130) from None
    console.print(
        f"\n  [green]✓[/] {len(result.intervals)} intervals set → https://intervals.icu/activities/{activity_id}"
    )
    console.print(f"  [dim]Undo with: {undo}[/]\n")


if __name__ == "__main__":
    main()
