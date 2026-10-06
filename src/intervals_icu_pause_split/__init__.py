"""Split intervals.icu activities into moving and pause intervals.

Use it from the command line (``intervals-icu-pause-split``) or as a library:

    from intervals_icu_pause_split import Client, Options, apply, plan

    with Client(access_token=token) as client:
        p = plan(client, "i87942121", Options.parse(edges="5km"))
        preview = p.to_dict()
        if p.has_changes:
            result = apply(client, p)
"""

__version__ = "0.2.0"

from .client import Client  # noqa: E402
from .detect import Segment, Stats, Streams, Summary, build_segments, find_pauses  # noqa: E402
from .errors import AuthError, DataError, IntervalsError, NotFoundError, PauseSplitError  # noqa: E402
from .plan import Options, Plan, Result, apply, plan, plan_restore  # noqa: E402
from .units import Edge, parse_activity_id, parse_duration, parse_edges  # noqa: E402

__all__ = [
    "AuthError",
    "Client",
    "DataError",
    "Edge",
    "IntervalsError",
    "NotFoundError",
    "Options",
    "PauseSplitError",
    "Plan",
    "Result",
    "Segment",
    "Stats",
    "Streams",
    "Summary",
    "apply",
    "build_segments",
    "find_pauses",
    "parse_activity_id",
    "parse_duration",
    "parse_edges",
    "plan",
    "plan_restore",
]
