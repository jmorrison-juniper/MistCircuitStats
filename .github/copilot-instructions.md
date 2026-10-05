# MistCircuitStats agent instructions

This file holds the rules that apply to MistCircuitStats only. The rules that apply to each
repository of this owner are in `AGENTS.md` at the repository root. Read `AGENTS.md` first. This
file adds to it, and it does not hold a copy of a rule from it. Where the two files disagree, obey
`AGENTS.md` for a writing rule, a safety rule, or a security rule.

## What this repository is

MistCircuitStats is a Python web dashboard for Juniper Mist network operators. It displays gateway
WAN port status, traffic, and health data in a browser. The app runs on Python 3.13 or newer and in
Linux containers.

## Language and environment

Use Python 3.13 or newer. Install application and development tools in a worktree with:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt -r requirements-dev.txt
```

Copy `.env.example` to `.env` for a local run. Set the required `MIST_APITOKEN` to a read-only Mist API token.
Set `MIST_ORG_ID` only when you do not want the app to detect the organization. `MIST_HOST` defaults
to `api.mist.com`. `PORT` defaults to `5000`. `LOG_LEVEL` defaults to `INFO`.

## Local gates

Run these commands from the repository root after you install the development tools.

| Gate | Command | Expected result |
| - | - | - |
| Ruff lint | `ruff check .` | No findings |
| Black format | `black --check .` | All files pass |
| Python compile | `python -m compileall -q app.py mist_connection.py docs tests` | No syntax errors |
| Type check | Not configured | The repository has no local type-check command |
| Bandit | `bandit -r . -ll -x ./.github,./.specify,./.venv,./.venv-ste,./.venv-ste-ci,./docs,./specs,./templates` | No findings |
| Dependency audit | `pip-audit -r requirements.txt` | No known vulnerabilities |
| Complexity | `radon cc . -j --exclude '.github/*,.specify/*,.venv/*,.venv-ste/*,.venv-ste-ci/*,docs/*,specs/*,templates/*' \| complexity-gate --max 15` | No function exceeds 15 |
| Dead code | `vulture . --min-confidence 90 --exclude .github,.specify,.venv,.venv-ste,.venv-ste-ci,docs,specs,templates` | No findings |
| Docstring coverage | `interrogate -v .` | At least 90 percent |
| Docstring style | `pydoclint .` | No findings |
| Offline tests | `python -m pytest -q` | All tests pass |
| Container build | `podman build --build-arg BUILD_DATE="$(date -u +'%y.%m.%d.%H.%M')" --build-arg VERSION=local-test -t mistcircuitstats:local-test .` | Image builds |
| STE lint | `ste-linter --config .ste-linter.toml --min-score 80 README.md docs/customer_response_wan_insights.md .github/PULL_REQUEST_TEMPLATE.md AGENTS.md .github/copilot-instructions.md` | Each file scores at least 80 |

The shared quality workflow runs only the gates enabled in `.github/workflows/quality-gates.yml`.
The repository does not enable a mypy gate.

## Architecture and conventions

`app.py` creates the Flask app and its JSON routes. `mist_connection.py` calls the Mist API through
the `mistapi` SDK. `templates/index.html` holds the browser UI, which uses Bootstrap 5.3.2, a dark
theme, and the `#E20074` accent color. The UI filters gateways and shows toast messages. Gateway
cards use three columns at medium screen sizes. The page adapts to iPad landscape screens and uses
inline JavaScript.

Keep calls to the Mist API in `MistConnection`. SDK responses expose `status_code` and `data`.
Accept a response only when `status_code` is `200`. Check that `org_id` has a value before a Mist
API call. Check the installed SDK signature before changing an API call. The tested Mist SDK range
is `mistapi>=0.64.0,<0.65`. It requires `python-dotenv>=1.1.0`; keep the runtime requirement
compatible. The app reads `MIST_APITOKEN`, `MIST_ORG_ID`, and `MIST_HOST` before it creates the
Mist connection.

The offline test fixtures set test credentials and mock Mist API responses. Do not use live
credentials or live API requests in a test.

## Safety in this repository

The app reads Mist organization and gateway data. Use a read-only API token for local development.
The app does not write data to Mist.

## Containers and ports

The repository has two Compose files. `docker-compose.yml` runs the published image, and
`docker-compose.dev.yml` builds the local image. Compose does not set a project name. Use
`mistcircuitstats-<issue-or-pr>` as the project name for each test stack. Both files publish
container port `5000` on host port `5000`. The files set fixed container names
`mistcircuitstats` and `mistcircuitstats-dev`, so they cannot run parallel test stacks safely.
Do not start a test stack from these files until the names and ports can change. Stop a local stack
with `docker compose -f docker-compose.dev.yml down --remove-orphans`.

The Dockerfile uses Python 3.13, runs as `appuser`, and checks `/health`. The shared container
workflow builds `linux/amd64` and `linux/arm64` images. It uses the `YY.MM.DD.HH.MM` version format
in UTC and sets OCI labels. The published image is
`ghcr.io/jmorrison-juniper/mistcircuitstats`.

## Git and GitHub in this repository

Use the `documentation` label for documentation changes.
The pull request template is `.github/PULL_REQUEST_TEMPLATE.md`. The project keeps its release
history in `docs/CHANGELOG.md`.

The workflows live in `.github/workflows/`. `quality-gates.yml` runs offline tests and quality
checks. `codeql.yml` runs CodeQL. `ste-lint.yml` grades the root README, the two agent instruction
files, the pull request template, and the WAN Insights response document. The repository requires
17 status checks on pull requests. It enables the `auto-merge` label after all required checks pass.
The container workflow publishes multi-architecture images to GHCR.

## Known pitfalls

- Issue [#16](https://github.com/jmorrison-juniper/MistCircuitStats/issues/16) fixed an invalid
  `start` argument to `searchOrgSwOrGwPorts`. Do not add that argument again.
- Issue [#17](https://github.com/jmorrison-juniper/MistCircuitStats/issues/17) fixed a full device
  UUID passed as a MAC address. Pass the 12-character MAC value to the SDK.

## Key files

| File | Purpose |
| - | - |
| `app.py` | Flask routes and app setup |
| `mist_connection.py` | Mist API calls and data conversion |
| `templates/index.html` | Browser dashboard |
| `tests/` | Offline route, time-window, and documentation tests |
| `docs/guide.md` | Setup, API, and quality gate details |
| `docs/CHANGELOG.md` | Release history |
| `.github/workflows/` | CI and release workflows |

## Spec Kit context

Read `.specify/memory/constitution.md` for the Spec Kit context. It still contains template
placeholders. No `update-agent-context` script exists, so Spec Kit does not write agent files here.

## External resources

The app uses the [Mist API](https://api.mist.com/api/v1/docs/Home) through the
[`mistapi` SDK](https://pypi.org/project/mistapi/). See the [detailed guide](../docs/guide.md)
for API endpoints and setup.
