# RPA Job Vacancy Bot

A UiPath-style unattended robot that collects **live** job vacancies from real
job boards, extracts title / company / location / salary / skills / description,
and writes a formatted, filterable Excel report.

No sample data: every run reads current listings from public job feeds. The
default configuration keeps **India** vacancies only; pass `--country none` for
a worldwide report.

```
INIT ──▶ GET TRANSACTION DATA ──▶ PROCESS TRANSACTION (retries) ──▶ REPORT
             (live portals)            (extract + normalise)        (Excel + log)
```

---

## Live sources

The default portal `all` aggregates live public sources with India-eligible roles:

| Source | Adapter | Transport | Notes |
| --- | --- | --- | --- |
| [Hasjob](https://hasjob.co/) | `hasjob` | Atom feed | India-focused startup board; every listing is India-based |
| [Shine](https://www.shine.com/) | `shine` | HTML | Indian job board; India-only search with pagination |
| [Internshala](https://internshala.com/) | `internshala` | HTML | Indian jobs/internships board |
| [Y Combinator Jobs](https://www.ycombinator.com/jobs) | `ycombinator` | HTML/JSON-like | YC company jobs filtered to India |
| [Himalayas](https://himalayas.app/) | `himalayas` | JSON API | Remote roles with `locationRestrictions`; pages deep for India |
| [Python.org Jobs](https://www.python.org/jobs/) | `python-jobs` | HTML | Python-specific board, detail pages enriched |
| [Remote OK](https://remoteok.com/api) | `remoteok` | JSON API | 100 newest remote jobs; needs link-back credit |
| [Working Nomads](https://www.workingnomads.com/api/exposed_jobs/) | `workingnomads` | JSON API | Remote roles with eligible-country lists |

Other adapters are registered but left out of the default run because probing
showed no India listings: `arbeitnow` (Europe-heavy), `jobicy` (no India geo
slug) and `weworkremotely` (regions are worldwide/Americas, never India). Run
them explicitly with `--portal <name> --country none` when you want them.

**Compliance notes:** LinkedIn is not scraped (robots.txt disallows all), Remotive API
is disallowed by robots, and Naukri requires reCAPTCHA. The bot respects `robots.txt`
and only uses publicly accessible feeds/endpoints.

Every registered adapter points at a real, public job feed; there is no demo or
sample board in the application, and `output/` only ever contains vacancies
collected from those live feeds.

Sources are queried with per-source budgets and the results are interleaved
round-robin, so one slow or failing feed cannot empty the report. Each row keeps
its `Portal`, `Apply URL` and `Source URL`, which satisfies the attribution
terms of the APIs in use.

### How the India filter works

Country filtering happens twice, both driven by `filters.countries`:

1. **Inside the adapters** — Hasjob marks every row as India; Himalayas checks
   `locationRestrictions`; Remote OK and Working Nomads scan their whole feed
   and keep matching rows *before* trimming to the run limit, so a low-ranked
   India listing is not missed.
2. **In the pipeline, before enrichment** — city and state aliases
   (`Bengaluru`, `Bangalore`, `Mumbai`, `Gurugram`, `Kerala`, `Telangana`, …)
   count as India, while word-boundary matching stops `Indiana`/`Indianapolis`
   false positives. Only surviving rows get detail-page requests.

A posting is kept when its location names India (directly, through an alias, or
via an explicit `location_country` such as Hasjob's `Anywhere`). Missing
locations are shown as `Not specified` but do not match a country filter.

---

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python3 run_bot.py                 # up to 50 live India vacancies from all sources
```

Output lands in `output/job_vacancies_all_<timestamp>.xlsx`.

Three front-ends share the same bot:

```bash
python3 run_bot.py                 # command line
python3 gui_bot.py                 # desktop (tkinter)
python3 web_bot.py                 # local web console → http://127.0.0.1:5000
```

---

## Web interface

```bash
python3 web_bot.py
# Open http://127.0.0.1:5000
```

The web console is a thin Flask wrapper around `JobBot`: it builds the run
configuration, starts the robot in a background thread and streams progress
back to the browser. The interface is an **IBM Carbon-themed RPA console**
with IBM Plex fonts, Carbon color tokens/icons, flat components, a 48px
header/sidenav, workflow flow indicator, source coverage panel, and a
light/dark theme toggle that remembers your choice.

What it shows:

* **Run form** — source, max vacancies, country filter (pre-filled `India`),
  keywords + any/all mode, detail-page toggle, append mode, optional report
  filename and request delay.
* **Execution panel** — status pill, segmented progress bar with percentage,
  an eight-cell metrics grid (discovered / captured / duplicates / outside
  filter / keyword drops / failed / total / duration) and the UiPath-style
  transaction log, with line numbers, timestamps and colour-coded levels.
* **Collected vacancies** — table of the run's rows with company, location,
  work mode, employment type, salary, posted date, source badge and apply link.
* **Report library** — every `.xlsx` in `output/`, newest first, with size,
  timestamp and a one-click download.
* **Keyboard and theme** — `Ctrl`/`Cmd` + `Enter` starts a run; the moon/sun
  button in the rail switches light/dark, and `?theme=dark` or `?theme=light`
  forces a theme for screenshots.

Server options:

```bash
python3 web_bot.py --port 8080
python3 web_bot.py --host 0.0.0.0 --port 8080     # expose on the LAN
python3 web_bot.py --config config/config.json
```

Endpoints: `GET /api/status`, `POST /api/run`, `GET /api/reports`,
`GET /reports/<name>.xlsx`, `GET /healthz`.

Only one run happens at a time; a second start returns HTTP 409. The server has
**no authentication** and binds to `127.0.0.1` by default — do not expose it to
an untrusted network. Downloads are restricted to `.xlsx` files inside the
configured output directory.

---

## Command line

```bash
# Collect up to 100 live India vacancies
python3 run_bot.py --limit 100

# India only, Python roles (repeatable / comma-separated)
python3 run_bot.py --keyword python
python3 run_bot.py --keyword "python, django" --match all

# Another country, or worldwide (clears the India default)
python3 run_bot.py --country "United Kingdom"
python3 run_bot.py --country none

# One source only, faster run without detail pages
python3 run_bot.py --portal hasjob --limit 20 --no-details

# Incremental: merge into an existing workbook and skip duplicates
python3 run_bot.py --append --output output/weekly_jobs.xlsx

# Tune politeness
python3 run_bot.py --delay 1.0

# Inspect adapters
python3 run_bot.py --list-portals
```

| Flag | Description |
| --- | --- |
| `--portal NAME` | `all` (default), `hasjob`, `shine`, `internshala`, `ycombinator`, `himalayas`, `remoteok`, `workingnomads`, `python-jobs`, `weworkremotely`, `arbeitnow`, `jobicy` |
| `--limit N` | Maximum rows written to the report (default 50) |
| `--country NAME` | Keep only vacancies in this country; repeat or comma-separate for several. `none` clears the filter (India is the default) |
| `--keyword WORD` | Keep only vacancies whose title, company, location, category, skills or description match. Repeat or comma-separate for OR; add `--match all` for AND |
| `--match any\|all` | Keyword combination mode (default `any`) |
| `--append` | Merge with an existing report, skip already-recorded vacancies |
| `--output PATH` | Explicit `.xlsx` destination |
| `--no-details` | Skip per-job detail pages (fewer fields, faster) |
| `--delay SECONDS` | Minimum wait between requests to the same host |
| `--config PATH` | Alternate JSON configuration |
| `--verbose` | Debug logging |

Because most feeds are global, a country filter collects a deeper pool than the
report limit (up to 8× the limit, capped at 300) and filters it before opening
detail pages. The actual row count can still be below `--limit`: the report only
contains vacancies that exist on the live boards at that moment.

---

## The Excel report

Three sheets are written on every run:

**Jobs** — one row per vacancy: Job ID, Job Title, Company, Location, Work Mode,
Employment Type, Salary, Posted Date, Category, Skills, Description,
Apply URL, Source URL, Portal, Scraped At. Header row frozen, autofilter/table
enabled, clickable links, dates stored as real Excel dates.

**Summary** — run metadata (start, finish, duration, portal, country and
keyword filters), result counts (discovered, new, duplicates, outside the
location filter, keyword-filtered, failed, total), jobs per source, top
companies / locations / skills, and the data-source & compliance note.

**Run Log** — UiPath-style transaction log: timestamp, level, status
(`Successful` / `Skipped` / `BusinessException` / `SystemException`), step
(`INIT`, `GET DATA`, `PROCESS`, `FILTER`, `REPORT`, `END`), job, attempt,
duration in ms, message. Timings and retries are visible per transaction.

---

## Scheduling unattended runs

Use `--append` with a fixed output filename so each run grows one workbook
instead of creating a new file.

**Linux / macOS (cron)** — every weekday at 07:30:

```cron
30 7 * * 1-5 cd /path/to/job && /path/to/.venv/bin/python run_bot.py --limit 100 --append --output output/weekly_jobs.xlsx >> output/cron.log 2>&1
```

**Windows Task Scheduler**:

```
Program:   C:\path\to\.venv\Scripts\python.exe
Arguments: run_bot.py --limit 100 --append --output output\weekly_jobs.xlsx
Start in:  C:\path\to\job
Trigger:   Daily 07:30
```

**systemd timer** (Linux):

```ini
# ~/.config/systemd/user/job-bot.service
[Service]
Type=oneshot
WorkingDirectory=%h/path/to/job
ExecStart=%h/path/to/job/.venv/bin/python run_bot.py --limit 100 --append --output output/weekly_jobs.xlsx
```

```ini
# ~/.config/systemd/user/job-bot.timer
[Timer]
OnCalendar=*-*-* 07:30:00
Persistent=true

[Install]
WantedBy=timers.target
```

Enable with `systemctl --user enable --now job-bot.timer`.

Exit codes: `0` success, `1` business/network failure, `2` unexpected error,
`130` interrupted. Cron/Task Scheduler can alert on non-zero.

---

## Configuration

`config/config.json` controls defaults; every CLI flag overrides it.

```json
{
  "portal": "all",
  "filters": { "keywords": [], "countries": ["India"], "match": "any" },
  "crawl": {
    "max_items": 50,
    "fetch_details": true,
    "delay_seconds": 0.4,
    "timeout_seconds": 20,
    "retries": 3,
    "backoff_seconds": 1.2,
    "respect_robots": true,
    "user_agent": "RPAJobBot/1.0 (personal job-search automation)"
  },
  "output": {
    "directory": "output",
    "filename_prefix": "job_vacancies",
    "description_limit": 1200,
    "skills_limit": 12
  },
  "skills": [ { "label": "Python", "patterns": ["python"] } ],
  "portals": {
    "all": { "sources": ["hasjob", "himalayas", "python-jobs", "remoteok", "workingnomads"] },
    "hasjob": { "base_url": "https://hasjob.co/feed" },
    "himalayas": {
      "base_url": "https://himalayas.app/jobs/api",
      "page_size": 20,
      "max_pages": 60
    },
    "remoteok": { "base_url": "https://remoteok.com/api" },
    "workingnomads": { "base_url": "https://www.workingnomads.com/api/exposed_jobs/" },
    "python-jobs": { "base_url": "https://www.python.org/jobs/", "max_pages": 1 }
  }
}
```

Set `filters.countries` to `[]` for a worldwide run, or to another country name
to reuse the same report for a different market. The GUI exposes the same field
(pre-filled with `India`).

Edit `skills` to change which technologies appear in the **Skills** column and
the Summary's skill breakdown.

---

## Politeness and compliance

* `robots.txt` is fetched and honoured per host; disallowed URLs raise a
  permanent error instead of retrying.
* Requests are throttled per host (`--delay`, and any `Crawl-delay` advertised
  in `robots.txt`, e.g. Remote OK's 1 second).
* Transient failures (5xx, 429, timeouts) use exponential backoff with jitter;
  4xx responses are not retried.
* Only publicly listed vacancy data is stored. Remote OK requires a followable
  link back and source credit; Jobicy requires clear credit and direct
  application links. Keep the `Portal`, `Apply URL` and `Source URL` columns
  when sharing the workbook.
* Check each source's terms before high-frequency scheduled runs; if a site
  objects, remove its adapter from the `all` source list.
* Some feeds ship double-encoded text (UTF-8 read as cp1252). The bot repairs
  these sequences and forces UTF-8 for JSON/XML responses so accents and
  curly quotes stay intact.
* python.org serves every current job on one page and answers `404` for
  `?page=2`; the adapter treats that as "pagination finished" instead of
  failing the run.

---

## Project layout

```
run_bot.py                 CLI entry point (UiPath Main.xaml equivalent)
gui_bot.py                 optional tkinter front-end
web_bot.py                 local Flask web console
config/config.json         portals, filters, crawl and output settings
rpa_jobs/
  cli.py                   argument parsing, overrides, terminal summary
  config.py                defaults + deep-merge config loader
  filters.py               country aliases (India cities/states) + keyword matching
  http_client.py           throttled, robots-aware, retrying HTTP client
  extractors.py            HTML→text, dates, salary, skills, mojibake repair (parse_posted_date)
  models.py                JobPosting / LogRecord dataclasses
  pipeline.py              REFramework-style discovery + per-item retries
  report.py                three-sheet Excel writer / append reader
  webapp.py                web routes, background run state, JSON API
  web/
    templates/
      index.html           IBM Carbon-themed RPA console markup
      _icons.html          Carbon icon sprite
    static/
      app.css              Carbon design system, light + dark themes
      app.js               Carbon UI behavior (polling, rendering, theme/nav)
      fonts/               IBM Plex Sans/Mono (vendored)
      icon.svg             favicon and brand mark
  portals/
    base.py                BasePortal contract + BusinessException
    aggregate.py           `all` fan-out and round-robin merge
    hasjob.py              India Atom feed
    shine.py               Shine India HTML board
    internshala.py         Internshala India HTML board
    ycombinator.py         Y Combinator India jobs (filtered)
    himalayas.py           remote JSON API, India locationRestrictions
    remoteok.py            live JSON API
    workingnomads.py       live JSON API
    weworkremotely.py      RSS feeds
    python_jobs.py         python.org HTML board
    arbeitnow.py           live JSON API (not in the India default)
    jobicy.py              live JSON API (not in the India default)
tests/
  fixtures/                offline HTML/fixtures for portals
  offline pytest suite + saved live API fixtures
output/                    generated .xlsx reports
```

---

## How the RPA pattern maps

| UiPath concept | This project |
| --- | --- |
| `Main.xaml` | `run_bot.py` → `JobBot.run()` |
| Orchestrator queue / transaction item | `JobPosting` draft per vacancy |
| Get Transaction Data | `BasePortal.discover()` |
| Process Transaction | `BasePortal.enrich()` + `derive_fields()` |
| BusinessException | Invalid/empty vacancy — skipped, run continues |
| SystemException + retries | Network/parse failure — retried with backoff |
| Config asset | `config/config.json` + dataclass models |
| Logs | console + **Run Log** sheet with step, attempt and duration |

---

## Tests

```bash
python3 -m pytest -q
```

The suite is fully offline: live API/RSS responses are saved under
`tests/fixtures/`, so adapters, extraction rules, filtering, retries, append
mode and the Excel writer are verified without network access.

---

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `All live sources failed` | No network, blocked host, or every adapter disabled. Check one portal: `python3 run_bot.py --portal hasjob --limit 5` |
| `Blocked by robots.txt` | The host disallows that path for our user agent. Use another source or leave `respect_robots` on |
| Fewer rows than `--limit` | Normal for India-only runs: the live boards currently hold fewer India vacancies than the limit. Check the `Vacancies discovered` / `Outside location filter` counts in the Summary and Run Log |
| No rows at all | The boards may have no India listings right now, or a keyword filter removed them. Try `--country none` or drop `--keyword` to confirm discovery works |
| Accents show as `Ã©` / `â€™` | Update to the current version; decoding and `repair_mojibake` handle this |
| `append` finds nothing new | All fetched vacancies already exist in the workbook. Use a fresh `--output` for a full snapshot |
| Web console: `Address already in use` | Port 5000 is taken. Start with `python3 web_bot.py --port 8080` |
| Web console: `A run is already in progress` | The bot allows one run at a time. Wait for the current run to finish, then start again |
| Web console: button stays on `Running…` | Check the terminal running `web_bot.py` for the traceback; the page also reports a lost connection after a few failed polls |
