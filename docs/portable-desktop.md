# Portable jav-data v1.0

Double-click `jav-data.exe`. Keep `_internal` beside it. Native Windows controls provide the UI; an embedded browser handles DMM and MGS. The internal API binds to loopback on an automatically selected port.

## First use

1. Connect your Japan VPN. It must cover jav-data and its downloads; a browser-only VPN extension is insufficient.
2. Open **Website Authentication**, select **DMM** or **MGS**, then **Open selected website**.
3. Complete age confirmation and any required login inside the embedded browser.
4. Click **I completed confirmation / login**.
5. Select the source in **Search Product URLs** or paste DMM/MGS URLs in **Scraping & Downloads**.
6. Select a library folder, queue URLs and browse the library.

Provide your Japanese IP environment yourself. A DMM account is needed for products that require login. Python, Qt and the browser runtime are bundled; no separate Python, Chrome, Edge or downloader installation is required. A fresh installation creates an empty database and browser profile. Updating application binaries preserves the existing configuration and collection.

MGS converts ABF-232 to distribution ID `abf00232` and saves the cover as `abf00232-fanart.jpg`. The original ID remains in manufacturer product ID. Conflicts with another website or original ID fail without overwriting existing products.

## Storage

Default `config.toml`:

```toml
[storage]
data_dir = "data"
library_dir = "library"
```

Paths resolve beside the configuration file. `data/` holds SQLite, logs and the browser profile. `library/` holds product-ID folders containing Japanese metadata, original covers and exported NFO. Cover names use the distribution ID followed by `-fanart` and the source image extension. Screenshots and trailers are no longer downloaded.

Add additional libraries in Database & Library. They share one database. The default library moves with the portable application; additional folders use absolute paths and must remain accessible. Changing configuration selects another location; it does not move existing files.

Libraries are named after their folders, with the full path shown alongside each name. Use **Remove** beside a library to unregister it and remove its movies from the app. Covers, metadata and NFO files stay on disk; adding the folder again restores its movies. Pending scrape jobs for that library stop, and old jobs cannot redirect to another library on retry. If all libraries are removed, add a folder before queuing new URLs.

Close jav-data before moving or backing up the entire application folder. Cookies are private account data. Keep `data/` out of GitHub. Moving between Windows accounts or computers may require login again.

Use **Refresh Library** in **Database & Library** to synchronize the database with on-disk `metadata.json` files. Adding a library also imports its existing metadata and covers. Deleted movie metadata removes the corresponding database record; unavailable drives or invalid metadata preserve existing records and show warnings. Files on disk are not deleted by refresh.

## Library and NFO

The Library columns are Cover, Release date, Product ID, Actresses, Title and Maker. Release date uses streaming release date data, and Product ID uses the distribution product ID. Drag header edges to resize columns, or drag headers to rearrange their order. Click any header except Cover to sort that field across all pages; click again to reverse direction. The arrow shows the active sort. Product URL search results and text export are sorted A–Z.

Library navigation shows up to ten clickable page numbers in both Table view and Cover view. **Previous** and **Next** move one page at a time. The numbered buttons switch groups when you cross a boundary: page 10 → 11 shows 11–20, and page 11 → 10 shows 1–10. The current page is highlighted. Enter an available page number in the field to the right of Next, then press **Enter** or **Go** to jump directly to it.

Use the **Cover view / Table view** buttons to switch Library views. Cover view uses a responsive grid of fixed 294 × 360 cards. Covers fit a fixed image area while preserving their aspect ratios, without cropping or stretching. Each card shows Product ID, streaming release date, a three-line title and two lines of cast names. Hover truncated text for the full value. Click a cover or double-click a card to open details. The **Sort by** selector chooses Title, Release date, Product ID, Actresses or Maker; the arrow button reverses the order across the whole library. Table headers still support sorting, resizing and rearranging. Both views share the same search, sorting and pagination.

The native desktop interface uses white surfaces, a pale gray sidebar and red accents. Movie details retain the centered cover area at approximately 60% of window height, with metadata in two columns and red clickable tags. The design uses lightweight native controls and cached line icons; it requires no additional software or online fonts.

Double-click a movie for metadata. The movie window supports minimize and maximize; opening another movie reuses and restores it. Click its cover to view the original. Emby NFO files export automatically during scraping and refresh after cover downloads. Artwork references the cover only.

Click an actress, director, series, maker, label, genre or related tag in movie details to return to Library and show movies with that exact value in the same field. Multiple names and tags have separate links. The current Table/Cover view and sorting stay selected, and results start on page 1. The active filter is shown above the results. Search narrows that filtered collection; **Clear filter** removes the metadata filter while retaining any typed search. Movie Previous/Next navigation follows the filtered results. The source URL is displayed as text.

Covers fit the available space in both movie details and the full-cover window, preserving aspect ratio and never exceeding the original image's physical pixel resolution. The full-cover window also supports minimize, maximize and close. Resizing either window automatically refits the cover.

History clearing hides finished jobs while preserving movie records and files. Cover downloads show list numbers in the ID column, rather than permanent database IDs. When the list is cleared, the next download starts at 1; active downloads remain listed. Active jobs remain visible. Cover downloads support pause, resume and retry; interrupted file transfers restart safely.

## Development and rebuilding

Install the development environment from the repository README. Close the application and run `scripts/build-portable.ps1`. It installs binaries into `portable/jav-data/` and preserves existing config, data and library. Copy the whole portable folder when moving it. Exclude personal data when sharing a clean build.

To create a separate clean build, use `scripts/build-portable.ps1 -OutputDirectory 'portable\jav-data-clean' -Fresh`. The output directory must not exist; this option never deletes an existing collection. Local application changes are tested and included in an updated portable build as part of the development workflow.

New scraping jobs automatically export movie.nfo after metadata is saved and refresh it after the cover download. Local cover filenames use <distribution-id>-fanart.jpg; the original DMM image URL is unchanged.

Movie detail covers occupy approximately 60% of the window height, centered and fitted without enlarging beyond the original resolution. Previous/Next buttons and Left/Right arrow keys follow the library search and sort order, including across result pages. Refresh metadata & cover queues the saved DMM or MGS product URL again; an unchanged completed cover is retained.

Library browsing uses small cached previews; original cover files remain unchanged and are used in movie details and the full-cover viewer. The embedded browser initializes when first needed. The performance review is recorded in the source repository's docs folder.
