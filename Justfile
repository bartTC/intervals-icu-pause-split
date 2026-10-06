# intervals-icu-pause-split

default:
    @just --list

# Run the test suite with coverage
test *ARGS:
    uv run pytest {{ARGS}}

# Coverage as a browsable HTML report
coverage:
    uv run pytest --cov-report=html
    @echo "open htmlcov/index.html"

# Show the preview, then ask before writing
run ACTIVITY *ARGS:
    uv run intervals-icu-pause-split {{ACTIVITY}} {{ARGS}}

# Show the preview, never write
check ACTIVITY *ARGS:
    uv run intervals-icu-pause-split {{ACTIVITY}} --dry-run {{ARGS}}

# Build the distribution
build:
    rm -rf dist
    uv build

# Upload to PyPI (CI does this on a tag; this is the manual fallback)
publish: build
    uv publish
