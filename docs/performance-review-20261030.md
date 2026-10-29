# Responsiveness review — 30 October 2026

This review addresses browser-opening delays and repeated work in large queues.
It keeps the native Windows interface, persistent browser profile, library formats
and original cover downloader. No database migration or additional dependency is
needed.

## Findings and changes

1. Authentication previously called `goto()` before displaying its page. A slow
   image or other resource could leave the app saying “Working…” for up to the
   navigation timeout. The browser is now displayed before navigating, and the
   authentication controls return when the document is ready.
2. The Qt adapter discarded `wait_until="domcontentloaded"`. Search and scraping
   therefore waited for full page loading despite requesting an earlier point.
   The adapter now honors this mode using a per-navigation marker in Qt's isolated
   application world. Existing metadata-readiness checks still wait for dynamic
   content. Navigation timers and signals are released on completion, timeout,
   replacement and closing; an old document cannot satisfy the next ready check.
3. Background metadata pages downloaded and decoded web images, fonts and media.
   They now block those resource types, prefetches and favicons while retaining
   documents, styles, scripts and API requests. Authentication remains a full page
   with images and login controls. Automatic media playback requires interaction.
   Original cover files continue through the existing separate downloader.
4. Hidden authentication pages could continue running scripts indefinitely. They
   now enter Qt's Frozen state only when its recommended state permits it, and
   resume when shown. Worker pages and active navigation are kept running. The
   profile and login state remain intact; pages are never discarded by this policy.
5. Each worker asked SQLAlchemy for its first queued item without a SQL `LIMIT`.
   SQLAlchemy materialized the whole queue. Scrape, download and default browser
   target queries now use `LIMIT 1`. An unused old browser-close callback was removed.
6. Every progress change iterated all download table cells, and scraping changes
   rebuilt the table and Retry controls. Both now reuse rows and skip unchanged
   records. Automatic queue-column measurement is bounded to 100 rows. The history
   still includes all uncleared entries; selection and Retry callbacks are retained.

## Measurements

Synthetic offline measurements on the same Windows computer/runtime. These are
individual operations, **not** end-to-end website or whole-app timing claims.

| Operation | Before | After |
|---|---:|---:|
| Fetch next scrape among 20,000 queued (median of 3) | 202.77 ms | 0.22 ms |
| Fetch next cover among 20,000 queued (median of 3) | 201.33 ms | 0.27 ms |
| Queue ORM objects materialized per read | 20,000 | 1 |
| Update one cover among 10,000 rows | 210.47 ms | 5.62 ms |
| Subsequent cover layout processing | 27.71 ms | 3.21 ms |
| Update one scrape job among 100 rows | 40.24 ms | 0.49 ms |

Initial creation of 10,000 download rows still took about 261 ms in this test.
History retrieval still returns the full list while its page is visible. A virtual
table or a revision-based API could reduce very large histories further, but is
not required for the measured per-progress bottleneck addressed here.

The reproducible browser benchmark uses a warmed local page with an intentionally
delayed 1.8-second image response (three rounds). Median navigation completion:
full load **1,840.69 ms**, DOM-ready **114.59 ms**, background DOM-ready
**37.55 ms**. Each case executed its JavaScript and JSON fetch; the background case
sent no image request. These timings demonstrate removal of unnecessary waiting,
not a predicted speedup on DMM/MGS. Run
`.venv/Scripts/python.exe scripts/profile-browser.py --output build/browser.json`.

## Validation

Real embedded-Chromium regression tests use a local HTTP server and temporary
profiles. They verify DOM-ready completion while an image is still pending,
full-load semantics, script and fetch preservation, background image suppression,
fresh document markers, navigation replacement, timeout recovery, closing during
loading, timer cleanup, and freezing/resuming a hidden authentication page.

Worker tests use 1,105 queued records and ORM load-event counts to verify only the
oldest task is materialized; all remaining records stay queued. UI tests verify
updates only touch changed rows and preserve selection and Retry actions. Existing
metadata parsing, authentication, cover download, library and NFO checks remain
part of the regression suite.

The full suite passed **119 tests**. The six browser/desktop tests were then rerun
after the benchmark exposed Qt coalescing `loadStarted` during consecutive
navigations. Completion now uses a fresh document marker for both wait modes;
all six and all nine repeated benchmark navigations passed.

The staged portable executable passed its own offline check: five native screens,
embedded Chromium, cookie persistence, 50 Japanese cast entries and Emby NFO export.
Packaging now takes OpenSSL DLLs from the Python runtime instead of other tools on
PATH, and includes the managed runtime's required adjacent CA-policy resource.
TLS verification remains enabled. Packaged application bytecode was compared with
the current source before deployment.

Live DMM/MGS timing was not measured: VPN latency, server response time and site
changes remain independent factors. Network interception leaves metadata URLs in
the DOM, but a future site layout that derives metadata from an image-load event
could require an adapter adjustment. The cold first browser initialization still
starts Chromium; this change reduces its ongoing work rather than replacing it.

Qt API references: [DocumentReady and isolated script worlds](https://doc.qt.io/qtforpython-6.11/PySide6/QtWebEngineCore/QWebEngineScript.html),
[page lifecycle and request interception](https://doc.qt.io/qtforpython-6.11/PySide6/QtWebEngineCore/QWebEnginePage.html).
