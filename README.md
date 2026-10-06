# intervals-icu-pause-split

Splits an [intervals.icu](https://intervals.icu) activity into riding blocks
and pauses, so a café stop or a night in a hotel no longer drags down the
averages of the block it sits in.

```
uvx intervals-icu-pause-split https://intervals.icu/activities/i181405932 --api-key=YOUR_KEY
```

That is the whole install. `uvx` fetches it, runs it, and throws it away again.
Pass the activity id or just paste its URL.

## What it looks like

A two-day bikepacking trip, recorded as one activity with auto-pause on:

```
╭──────────── intervals.icu · i181405932 ────────────╮
│ Wochenendausflug                                   │
│ Sat 06:30, 2026-08-29 · 352.0 km · 35:04 h elapsed │
╰────────────────────────────────────────────────────╯
  Pause: at least 5 min below 3 km/h or not recording; stops less than 1 min apart are merged
  Warmup: first 10 min of riding · Cooldown: last 10 min

Speed     │▇▇▇▇▇▇▇▇▇▆▆▆▆▆▆▆▃▅▆▆▆▇▇▆▅▆                                      ▆█▇▆▇▇▇▆▆▆▆▇██▇█▇▇▆▆██▇▇│
Now       │████████████████████████████████████████████████████████████████▓█████████████████████▓▓│
New       │█▓▓▓▓▓▓▓▓░░████░░▓▓░█████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░▓▓▓▓▓▓░███░░▓▓▓▓▓▓░░██▓│
          └──────┴──────┴───────┴──────┴───────┴──────┴───────┴──────┴───────┴───────┴──────┴──────┘
                 09:00  12:00   15:00  18:00   21:00  Sun     03:00  06:00   09:00   12:00  15:00
           █▓ ride   ░ pause   ▁…█ speed up to 24 km/h

Now
 #  Type  Label      Start  Duration  Distance  km/h    W
 1  WORK  —      Sat 06:30   25:50 h  178.2 km  18.2  113
 2  WORK  —      Sun 08:21     3 min    1.7 km  27.7   45
 3  WORK  —      Sun 08:24    8:30 h  159.1 km  20.6  105
 4  WORK  —      Sun 16:54    39 min   13.1 km  19.9  123

New
 #  Type      Label         Start  Duration  Distance  km/h    W
 1  WORK      Warmup    Sat 06:30    10 min    3.6 km  21.4  123
 2  WORK      Ride 1    Sat 06:40    3:40 h   72.1 km  19.7  121
 3  RECOVERY  —         Sat 10:20    11 min    0.0 km     —    —
 4  WORK      Ride 2    Sat 10:32    2:16 h   40.4 km  18.0  111
 5  RECOVERY  —         Sat 12:49    11 min    0.2 km     —    —
 6  WORK      Ride 3    Sat 13:00    1:05 h   14.8 km  15.1   81
 7  RECOVERY  —         Sat 14:05    14 min    0.0 km     —    —
 8  WORK      Ride 4    Sat 14:20    2:26 h   41.8 km  17.5  117
 9  RECOVERY  —         Sat 16:47   15:15 h    0.2 km     —    —
10  WORK      Ride 5    Sun 08:02    3:01 h   59.3 km  20.2  103
11  RECOVERY  —         Sun 11:04     6 min    0.2 km     —    —
12  WORK      Ride 6    Sun 11:11    1:25 h   24.6 km  18.9   92
13  RECOVERY  —         Sun 12:36    11 min    0.0 km     —    —
14  WORK      Ride 7    Sun 12:47    2:57 h   60.9 km  20.8  109
15  RECOVERY  —         Sun 15:45    15 min    0.0 km     —    —
16  WORK      Ride 8    Sun 16:00    1:23 h   30.7 km  22.1  122
17  WORK      Cooldown  Sun 17:24    10 min    3.2 km  19.4  124
  10 rides · 18:37 h · 351.5 km   |   7 pauses · 16:26 h

  Replace the 4 intervals with these 17? [y/n] (n):
```

`Now` is what the activity has, `New` what it will get. The first interval used
to run for 25 hours including the night; now the night is a pause of its own
and every block gets honest averages. Every interval gets at least one column,
so a ten-minute stop stays visible even on a two-day timeline.

## How pauses are found

- **Standing still:** slower than `--stop-speed` (3 km/h).
- **Not recording:** auto-pause leaves no samples, just a jump in the time
  stream. That counts as standing still too.
- **Merged:** stops with less than `--merge` (60 s) of riding between them are
  one pause. Wheeling the bike from the café back to the road does not split it
  in two.
- **Long enough:** a pause needs `--min-pause` (5 min) of actual standstill. The
  riding between merged stops does not count towards that, so stop-and-go
  through town stays riding.

Riding out of town and back in can be split off as well: `--edges 10m` turns
the first and last ten minutes of riding into `Warmup` and `Cooldown`
intervals. Give a distance instead with `--edges 3km`, or two values to set
start and end separately: `--edges 3km 10m`. A distance ignores the time spent
at traffic lights, so it tends to match "until I'm out of town" better.

## What gets written

Only the riding blocks, as labelled WORK intervals. intervals.icu fills the
gaps between them with RECOVERY intervals by itself. It does not accept
RECOVERY intervals through the API (they come back as WORK), and it drops any
label on them, which is why the pauses in the table have none.

Writing replaces **all** intervals on the activity. Before that, the current
ones are saved to `~/.local/state/intervals-icu-pause-split/backups/` (or
`$XDG_STATE_HOME`), and the tool prints the command that puts them back:

```
uvx intervals-icu-pause-split i181405932 --restore ~/.local/state/intervals-icu-pause-split/backups/i181405932-20261006-044729.json
```

## Usage

```
uvx intervals-icu-pause-split i181405932                   # preview, then ask before writing
uvx intervals-icu-pause-split i181405932 --dry-run         # preview, never write
uvx intervals-icu-pause-split i181405932 --min-pause 10m   # only the longer stops
uvx intervals-icu-pause-split i181405932 --edges 10m       # warmup and cooldown of 10 minutes
uvx intervals-icu-pause-split i181405932 --edges 3km 10m   # 3 km warmup, 10 minute cooldown
uvx intervals-icu-pause-split i181405932 --label Fahrt     # "Fahrt 1", "Fahrt 2", …
uvx intervals-icu-pause-split i181405932 --yes             # write without asking
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
| `--merge` | `60s` | Stops with less riding than this in between count as one pause |
| `--stop-speed` | `3` | Below this speed (km/h) you count as standing still |
| `--edges` | | Split off the first and last stretch of riding as `Warmup` and `Cooldown`, as a duration (`10m`) or a distance (`3km`); one value for both ends or two for start and end |
| `--label` | `Ride` | Label prefix for the riding intervals |
| `--width` | terminal width | Width of the timeline |
| `--restore` | | Put back the intervals from a backup file |
| `--dry-run` | | Show the preview, never write |
| `--yes` | | Skip the confirmation prompt |

## Development

```
just test                      # run the suite with coverage
just coverage                  # the same, as a browsable HTML report
just check i181405932          # dry run against your own account
just run i181405932            # run for real, with the confirmation prompt
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
