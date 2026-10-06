# Changelog

All notable changes to this project are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [0.2.0] - 2026-10-06

The package can now be used as a library, e.g. from a web service. The command
line behaves and prints exactly as in 0.1.0.

### Added

- `Client(api_key)` or `Client(access_token=...)` for intervals.icu, the latter
  for OAuth tokens of a service acting on behalf of other athletes.
- `plan()` reads an activity (id or URL) and proposes the split without
  writing; `apply()` writes it; `plan_restore()` puts back earlier intervals.
- `Plan.to_dict()`: a JSON-ready preview with both interval lists, per-interval
  start, duration, distance, average speed and power, a summary, and the speed
  over time for drawing a chart.
- `Options` (seconds and km/h) and `Options.parse()`, which takes the same
  strings as the command line (`"5m"`, `"3km,10m"`).
- Exceptions instead of exiting: `AuthError`, `NotFoundError`,
  `IntervalsError`, `DataError`, all derived from `PauseSplitError`.
- A "Use it as a library" section in the README.

### Changed

- The code is split into modules: `detect`, `client`, `plan`, `render`, `units`
  and `cli`. Anything imported from `intervals_icu_pause_split.cli` in 0.1.0
  now lives in one of the others; import it from the package instead.

## [0.1.0] - 2026-10-06

First release.

### Added

- Split an activity into moving legs and pauses. A pause is standing still or
  not recording (auto-pause), for at least `--min-pause` (default 5 min).
  Stops less than `--merge` apart (default 60 s) count as one pause.
- Stop speed by sport: 1 km/h on foot (hike, walk, run), 3 km/h otherwise;
  `--stop-speed` overrides it.
- `--edges` splits off a warmup and cooldown, as a duration (`10m`), a
  distance (`5km`), or both separately (`3km,10m`).
- Preview before writing: a timeline drawn to scale with the speed, the
  current and the new intervals, plus tables of both.
- Only the moving legs are written, as labelled WORK intervals (`--label`,
  default `Leg`); intervals.icu derives the pauses from the gaps.
- Confirmation prompt, `--dry-run` and `--yes`; Ctrl-C is handled.
- The replaced intervals are backed up first, and `--restore` puts them back.
- Activity id or the full intervals.icu URL as argument.

[0.2.0]: https://github.com/bartTC/intervals-icu-pause-split/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/bartTC/intervals-icu-pause-split/releases/tag/v0.1.0
