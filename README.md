# intervals-icu-pause-split

Splits an [intervals.icu](https://intervals.icu) activity into moving legs
and pauses, so a café stop, a lunch break on a hike or a night in a hotel no
longer drags down the averages of the leg it sits in. Works for rides, hikes,
walks and runs alike.

```
uvx intervals-icu-pause-split https://intervals.icu/activities/i87942121 --api-key=YOUR_KEY
```

That is the whole install. `uvx` fetches it, runs it, and throws it away again.
Pass the activity id or just paste its URL.

## What it looks like

A gravel ride on Rügen. intervals.icu had detected 97 intervals on its own:
power surges of a few seconds, with "recovery" in between, which says nothing
about how the ride actually went.

```
❯ uvx intervals-icu-pause-split --edges 5km https://intervals.icu/activities/i87942121

╭────────────────── intervals.icu · i87942121 ──────────────────╮
│ Sassnitz Gravel/Offroad-Radfahren                             │
│ GravelRide · Sat 10:58, 2025-05-17 · 96.9 km · 5:33 h elapsed │
╰───────────────────────────────────────────────────────────────╯
  Pause: at least 5 min below 3 km/h or not recording; stops less than 1 min apart are merged
  Warmup: first 5 km · Cooldown: last 5 km

Speed     │▄▅▆▇▇▇▇▆▅▃▄▄▅▆▆▄█▇███▅▇▇▁ ▅▇▆▇▇▇▇▇▇▆▇▆▇▆▆▆▄▆▄  ▄▇▇▆▇█▇▆▇▇▇█▇▇█▇▆▇▇▆▅▄▅▆▆▅█▅▅▅▅▇▇▆▅▆██▇██│
Now       │╎░╎╎╎╎█╎█╎╎█░░█████░░█░░░░░░░░░░░░░░░░░░░░░█░░░░░█╎░░░░░░█░░░█░░░░░░╎░█░╎█░░░░░╎█╎░╎╎╎█░│
New       │████████████████████████░░░█████████████████░░░█████████████████████████████████████████│
          └┴───────────────┴──────────────┴───────────────┴───────────────┴───────────────┴────────┘
           11:00           12:00          13:00           14:00           15:00           16:00
           ██ moving   ░ pause   ╎ shorter pause   ▁…█ speed up to 27 km/h   · one column ≈ 3 min

Now  97 intervals, 88 not shown
 #  Type      Label  Start  Duration  Distance  km/h    W
 1  RECOVERY  —      10:58     1 min    0.4 km     —    —
 2  WORK      —      11:00     3 min    0.7 km  11.3  255
 3  RECOVERY  —      11:04     5 min    1.5 km     —    —
 4  WORK      —      11:09       6 s    0.0 km  17.3  510
 5  RECOVERY  —      11:09     1 min    0.6 km     —    —
 6  WORK      —      11:11       5 s    0.0 km  20.8  418
 …  …         …          …         …         …     …    …
95  RECOVERY  —      16:23     1 min    0.7 km     —    —
96  WORK      —      16:25      10 s    0.1 km  27.1  468
97  RECOVERY  —      16:25     6 min    2.8 km     —    —

New
#  Type      Label     Start  Duration  Distance  km/h    W
1  WORK      Warmup    10:58    17 min    5.0 km  17.1  195
2  WORK      Leg 1     11:16    1:13 h   21.0 km  19.6  133
3  RECOVERY  —         12:29    10 min    0.0 km     —    —
4  WORK      Leg 2     12:40    1:06 h   22.0 km  19.8  148
5  RECOVERY  —         13:47    11 min    0.0 km     —    —
6  WORK      Leg 3     13:58    2:20 h   43.9 km  19.4  140
7  WORK      Cooldown  16:19    12 min    5.0 km  23.5   99
  5 legs · 5:11 h · 96.9 km   |   2 pauses · 21 min

  Replace the 97 intervals with these 7? [y/n] (n):
```

`Now` is what the activity has, `New` what it will get: 5 km out of town and
5 km back in as warmup and cooldown, three legs, and the two real stops
between them. A long `Now` list is cut down to its first and last few rows;
the timeline above it always shows everything.

The timeline is drawn to scale. A pause shorter than one column still shows up,
as a thin `╎`, so a short stop stays visible even on a two-day bikepacking
trip without looking longer than it was. In the terminal, consecutive legs alternate between
green and cyan.

## How pauses are found

- **Standing still:** slower than `--stop-speed`: 1 km/h on foot (hike, walk,
  run), 3 km/h for everything else. A steep climb on foot easily drops below
  3 km/h, while GPS drift at a real stop stays under 1 km/h.
- **Not recording:** auto-pause leaves no samples, just a jump in the time
  stream. That counts as standing still too.
- **Merged:** stops with less than `--merge` (60 s) of moving between them are
  one pause. Wheeling the bike from the café back to the road does not split it
  in two.
- **Long enough:** a pause needs `--min-pause` (5 min) of actual standstill. The
  moving between merged stops does not count towards that, so stop-and-go
  through town stays moving.

Getting out of town and back in can be split off as well: `--edges 10m` turns
the first and last ten minutes into `Warmup` and `Cooldown` intervals. Give a
distance instead with `--edges 5km`, or two values to set start and end
separately: `--edges 3km,10m`. A distance ignores the time spent at traffic
lights, so it tends to match "until I'm out of town" better.

## What gets written

Only the moving legs, as labelled WORK intervals. intervals.icu fills the
gaps between them with RECOVERY intervals by itself. It does not accept
RECOVERY intervals through the API (they come back as WORK), and it drops any
label on them, which is why the pauses in the table have none.

Writing replaces **all** intervals on the activity. Before that, the current
ones are saved to `~/.local/state/intervals-icu-pause-split/backups/` (or
`$XDG_STATE_HOME`), and the tool prints the command that puts them back:

```
uvx intervals-icu-pause-split i87942121 --restore ~/.local/state/intervals-icu-pause-split/backups/i87942121-20261006-044729.json
```

## Usage

```
uvx intervals-icu-pause-split i87942121                   # preview, then ask before writing
uvx intervals-icu-pause-split i87942121 --dry-run         # preview, never write
uvx intervals-icu-pause-split i87942121 --min-pause 10m   # only the longer stops
uvx intervals-icu-pause-split i87942121 --edges 10m       # warmup and cooldown of 10 minutes
uvx intervals-icu-pause-split i87942121 --edges 3km,10m   # 3 km warmup, 10 minute cooldown
uvx intervals-icu-pause-split i87942121 --label Etappe    # "Etappe 1", "Etappe 2", …
uvx intervals-icu-pause-split i87942121 --yes             # write without asking
```

Durations are written as `90s`, `5m` or `1.5h`; a bare number means minutes.
Distances for `--edges` are written in `km` (`0.5km`, not `500m`, because `m`
already means minutes).
Nothing is written without a confirmation prompt unless you pass `--yes`.

### Credentials

The API key sits at the bottom of <https://intervals.icu/settings>. Provide it
by flag, by environment variable, or in a `.env` file next to where you run it:

```
INTERVALS_ICU_API_KEY=your_key_here
```

### Options

| Flag | Default | Meaning |
| ---- | ------- | ------- |
| `--api-key` | `$INTERVALS_ICU_API_KEY` | Your intervals.icu API key |
| `--min-pause` | `5m` | Minimum standstill for a pause |
| `--merge` | `60s` | Stops with less moving than this in between count as one pause |
| `--stop-speed` | `1` on foot, `3` otherwise | Below this speed (km/h) you count as standing still |
| `--edges` | | Split off the first and last stretch as `Warmup` and `Cooldown`, as a duration (`10m`) or a distance (`3km`); one value for both ends or two, comma-separated, for start and end |
| `--label` | `Leg` | Label prefix for the moving intervals |
| `--width` | terminal width | Width of the timeline |
| `--restore` | | Put back the intervals from a backup file |
| `--dry-run` | | Show the preview, never write |
| `--yes` | | Skip the confirmation prompt |

## Use it as a library

Everything the command line does is available from Python, for example for a
web service that lets people pick an activity, shows the preview and writes it
when they confirm:

```python
from intervals_icu_pause_split import Client, Options, apply, plan, plan_restore

with Client(access_token=token) as client:  # or Client(api_key)
    p = plan(client, "https://intervals.icu/activities/i87942121", Options.parse(edges="5km"))
    preview = p.to_dict()  # JSON-ready, to draw your own preview
    if p.has_changes:
        result = apply(client, p)
        save_somewhere(result.previous)  # the intervals before the write

    # Later, to undo:
    apply(client, plan_restore(client, "i87942121", load_from_somewhere()))
```

- `plan()` only reads. It takes an activity id or URL and returns the current
  and the proposed intervals; `apply()` writes the proposal.
- `Options.parse()` takes the same strings as the command line (`"5m"`,
  `"3km,10m"`) and raises `ValueError` with a readable message, handy for form
  input. `Options(...)` takes seconds and km/h directly.
- `to_dict()` has the activity, both interval lists with start time, duration,
  distance, average speed and power per interval, a summary, and the speed over
  time in equal slices for drawing a chart.
- Errors are exceptions, never an exit or console output: `AuthError` (401/403),
  `NotFoundError` (404), `IntervalsError` (any other HTTP error, or the network),
  and `DataError` (the activity can't be split as asked). All of them derive
  from `PauseSplitError`.
- `Client` takes an API key, or an OAuth access token for a service acting on
  behalf of other athletes. It is synchronous; in FastAPI, declare the
  endpoints with `def` rather than `async def` so they run in the threadpool.

The lower-level pieces (`find_pauses`, `build_segments`, `Streams`, `Segment`)
are plain functions and dataclasses that work on lists, without any network.

## Development

```
just test                      # run the suite with coverage
just coverage                  # the same, as a browsable HTML report
just check i87942121          # dry run against your own account
just run i87942121            # run for real, with the confirmation prompt
just build                     # build the distribution
```

Releases are cut by tagging:

```
git tag v0.1.0 && git push --tags
```

CI runs the tests, refuses a tag that disagrees with the version in
`pyproject.toml`, and publishes to PyPI through Trusted Publishing, so no API
token is stored in the repository.

## License

MIT
