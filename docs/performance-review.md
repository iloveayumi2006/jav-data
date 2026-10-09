# Performance review — 5 October 2026

The main problems were oversized images retained for library previews, closed image
windows retaining their image data, and redundant work on each library load. These
have been addressed while preserving the existing screens, sorting, search,
navigation, original covers, authentication, scraping and automatic Emby export.

## Measurements

The comparison used the same Windows computer, a temporary snapshot of the existing
library, and read-only access to its original covers. The baseline application
modules came from the previous portable build. Both versions ran under the same
Python/Qt runtime. Each run started with an empty preview cache. No live DMM pages
were opened and no original database or library files were modified.

| Measurement | Before | After |
|---|---:|---:|
| Main process private memory after the first 24 movies | 443.0 MiB | 201.4 MiB |
| Startup through library images being ready | 4.97 s | 3.67 s |
| Initial local API/image requests | 50 | 26 |
| Initial image data transferred | 17.85 MiB | 2.81 MiB |
| Load page 2, including images | 3.01 s | 2.04 s |
| Return to page 1, including images | 2.16 s | 0.59 s |
| Dialog objects after eight full-cover windows were closed | 9 | 1 |
| Main process memory after the browsing sequence | 568.9 MiB | 236.0 MiB |

The one remaining dialog is the intentionally reused movie detail window. Startup
and page timings vary with Windows scheduling and file caching. They are indicative
measurements, not guaranteed times. Memory values are the application's main
process private bytes, excluding browser subprocesses. This review does not claim
improvements to live DMM response time. Cold first-window frame delays were variable
and did not consistently improve; they remain a candidate for future profiling.

## Findings and fixes

1. **High impact — full-resolution images used for every library preview.** A page
   retained 24 decoded originals and loaded nearly 18 MiB of compressed images.
   Library images now use previews bounded to 768 × 512, generated outside the UI
   thread and cached on disk. The UI's reusable preview cache is limited to 24 MiB,
   in addition to images currently displayed. Original files and full-resolution
   detail/viewer images are preserved. Source file changes invalidate disk previews;
   asset updates invalidate UI previews. Old disk versions are removed.
2. **High impact — closed full-cover dialogs were hidden, not destroyed.** Each
   retained a decoded original and its save-image data. These dialogs now delete
   themselves when closed; regression tests verify the objects are released.
3. **Medium impact — duplicate library work.** Hidden cards were created while the
   table was visible, and each movie required a separate cover-metadata request.
   Cards now build when selected. Cover references arrive with the library page,
   using one bulk query. Media delivery uses one database query without loading
   unrelated cast metadata. The obsolete per-movie thumbnail lookup was removed.
4. **Medium impact — previews could crowd out app controls.** Preview requests have
   a separate pool of two workers; normal controls use four workers. Page changes
   cancel pending obsolete requests and suppress stale results, including results
   already waiting for UI delivery. Movie navigation retains only nearby pages.
5. **Medium impact — unnecessary browser and polling work.** The browser profile and
   view are created when needed. Closing the displayed browser page deletes its view
   instead of creating a replacement blank page. Authentication cookies remain
   persistent. Identical queue results no longer rebuild tables, repeated status
   requests are coalesced, and polling pauses while the app is minimized.
6. **Smaller savings — repeated scraping and download work.** Scraping now retrieves
   page HTML once for metadata and cover extraction. Obsolete non-cover branching
   was removed. Download progress database updates are limited to four per second,
   with the exact final size still saved on completion.

## Validation and repeatability

The full suite passed: **56 tests**. Additional coverage checks preview dimensions,
portrait images, source preservation, concurrent generation, cache reuse and
invalidation, the media API query count, the UI cache memory bound, lazy cards and
browser creation, browser-view cleanup, destroyed cover dialogs, and cancellation
of stale requests. Navigation and native desktop tests were rerun after the final
navigation-cache change. Ruff checks also pass.

`scripts/profile-desktop.py --output build/performance/report.json` runs the offline
measurement with the project Python environment. Run it from the project directory
with a populated portable library. It snapshots the database, disables queued work
in the snapshot, and reads existing covers. It opens temporary test windows, then
closes them and removes the snapshot. `JAV_DATA_PROFILE_MODULES` optionally selects
another application-module directory for a comparison. The recorded comparison is
in `docs/performance-results.json`.

The portable executable has not been rebuilt during this review. The improvements
are in the source and will be included in the next requested portable build.
