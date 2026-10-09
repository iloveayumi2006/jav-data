# jav-data v1.0

A portable Windows desktop app for collecting DMM and MGS product metadata, original cover images, and Emby NFO files into a searchable local library. It uses a native interface and a built-in browser for website authentication, searching, and scraping.

Japanese titles and metadata are preserved as supplied by the source website. The interface and metadata field labels are in English.

## Download and requirements

Download **jav-data-v1.0-windows-x64.zip** from [jav-data-v1.0](https://github.com/iloveayumi2006/jav-data/releases/tag/v1.0), extract the whole archive, and open **jav-data.exe**. Source code and release downloads are available on GitHub. The ZIP is the ready-to-run app; GitHub’s source-code archives are for development.

You need:

- **64-bit Windows 10 or Windows 11.** The current build is tested on Windows 11 x64.
- **A working Japan IP connection.** Prepare your own Japan VPN or equivalent network environment before opening DMM or MGS. It must cover the desktop app and its downloads; a VPN extension confined to Chrome or Edge does not cover jav-data's embedded browser.
- **A DMM account for products that require sign-in.** Have your account ready and complete any required login in the embedded DMM browser.
- An internet connection and a writable location with space for your library.

The portable release includes Python, Qt, and its browser runtime. No separate Python, Chrome, Edge, or downloader installation is required. Keep the entire extracted folder together, including **_internal**.

The clean release contains no personal database, downloaded products, cookies, or saved login. An empty database and browser profile are created on first launch.

## 1. Authenticate with the source website

1. Connect your Japan VPN or establish your Japan IP environment.
2. Open **Website Authentication** in jav-data.
3. Select **DMM** or **MGS**, then click **Open selected website**.
4. Complete the selected website's age confirmation and any required account login in the browser inside the app.
5. Once the website is accessible, click **I completed confirmation / login**.

The session must be marked ready before searching or processing the scraping queue. **Close browser / pause queue** closes the authentication view and pauses scraping until the session is made ready again.

Cookies are stored locally to reuse the session. If either website asks you to confirm your age or log in again, repeat these steps and retry affected jobs. Account passwords are entered on the website's page, not in jav-data's configuration file.

## 2. Search for product URLs

1. Open **Search Product URLs**.
2. Select **DMM** or **MGS**, then enter an actress name, distribution/product ID, maker, or another search keyword. Japanese names usually give the most direct matches.
3. Click **Search** and wait for collection to finish.
4. jav-data follows the selected website's result pages, removes duplicate product URLs, sorts them A–Z, and displays **100 URLs per page**.
5. Use **Previous** and **Next** to browse the collected URLs.
6. Click **Copy this page** to copy the current batch, or **Save all collected URLs…** to save the full list as a text file.

This searches the selected website's keyword results. The **Library** search searches products already saved locally. URL search results last for the current app session; save the text list if you want to reuse it later.

## 3. Add URLs to scraping

1. Open **Scraping & Downloads**.
2. In **Paste product URLs**, paste one product URL per line. Each submission accepts up to **100 URLs**.
3. Choose the destination library folder from the dropdown.
4. Click **Add to scrape queue**.
5. Keep the website session ready. Metadata is collected first; cover downloads follow in the background.

For more than 100 results, copy and submit each search-results page as a separate batch. You can also paste supported product URLs copied directly from DMM or MGS, such as:

```text
https://video.dmm.co.jp/av/content/?id=PRODUCT_ID
```

Successful jobs create or update the movie in the library. Adding an existing Product ID updates that record instead of creating a second movie, while keeping its existing product-folder location. An unchanged completed cover is reused.

Use **Retry** for failed jobs after fixing the connection or session. Cover downloads have separate **Pause**, **Resume**, and **Retry** controls. Clearing finished queue/download history preserves the movies and their files. The cover-download ID column shows list numbers; after the list is cleared, the next download starts at 1. Active downloads remain listed.

## MGS identifiers and covers

MGS requires a **Japan IP**. Complete its age confirmation and any required login in **Website Authentication** before searching or scraping. DMM and MGS use the same embedded browser; their cookies remain scoped to their respective websites.

MGS IDs are converted into distribution IDs: **ABF-232 → abf00232**, **ABW-054 → abw00054**, **ABP-542 → abp00542**. The letters become lowercase and the numeric part is padded to at least five digits. The original MGS ID remains in the manufacturer product ID field. For example:

```text
https://www.mgstage.com/product/product_detail/ABF-232/
```

This creates `abf00232/metadata.json`, `abf00232/abf00232-fanart.jpg`, and `abf00232/movie.nfo`. The cover comes from the product's enlarged-image link, not its thumbnail. The full introduction is taken from the page's description metadata when available.

Only letters-number MGS IDs are currently supported. IDs containing numeric prefixes or extra suffixes are rejected with an explanation, rather than guessed. Search still lists those product URLs. An ID already belonging to the other website, or a different original MGS product ID, causes the scrape to fail without overwriting its metadata or files. Re-scraping the same MGS product updates the existing record.

## Database & Library

The **Database & Library** tab contains the shared database location and all registered libraries. **Add library folder…** scans the chosen folder immediately and imports existing movies from their `metadata.json` files, including available covers. Each movie must have its own folder named with its distribution ID.

Library names use the folder name; full paths distinguish folders with the same name. **Remove** unregisters a library and removes its movies from the app while keeping files on disk. Add the folder again to restore its movies. Pending scrape jobs for a removed library stop; add their URLs again to the desired library. You can remove every library, then add a folder before queuing new URLs.

In movie details, click an actress, director, series, maker, label, genre or related tag to show movies with that exact metadata value in Library. Each name or tag is linked separately. Your view and sorting are retained, and the filter starts on page 1. Search further within those results, or use **Clear filter** to remove the metadata filter. The source URL is displayed as text.

The desktop UI has white surfaces, a light gray sidebar and red accents. Switch between **Cover view** and **Table view** using the Library buttons. Use **Sort by** and the arrow button to choose a field and reverse its order; table headers also support sorting, resizing and rearranging. Movie details use a centered cover and two columns of metadata. No extra software is required for the interface.

Click **Refresh Library** to scan all registered libraries. New metadata is imported, changed metadata is updated, and movies whose `metadata.json` or movie folder has been deleted are removed from the database and library view. Refresh does not delete files on disk. Missing/unavailable library roots and damaged metadata are reported and their existing records are retained. Duplicate IDs present in another library are reported instead of silently replacing a movie. Movies moved between accessible registered libraries are picked up at their new location.

Scanning runs outside the UI thread and waits for active scraping/downloads to finish before making changes. The library view refreshes automatically when scanning completes.

## Automatic files and metadata

Every successfully scraped movie receives **movie.nfo** automatically. The Emby NFO is refreshed after its cover finishes downloading. There is no manual export step.

Products are stored in folders named with their distribution Product ID:

```text
jav-data/
├── jav-data.exe
├── _internal/                  bundled application runtime
├── config.toml                 storage settings
├── data/                       database, browser session, logs and previews
└── library/
    └── PRODUCT_ID/
        ├── metadata.json       original Japanese metadata
        ├── PRODUCT_ID-fanart.jpg
        └── movie.nfo           Emby metadata and cover reference
```

Covers use the highest-resolution original source discovered on the product page. JPG covers use **PRODUCT_ID-fanart.jpg**; other source formats retain their corresponding extension. Small cached previews make browsing faster without changing the original cover files.

Collected metadata includes:

| DMM field | Stored information |
|---|---|
| 配信開始日 | Streaming release date |
| 商品発売日 | Product release date |
| 収録時間 | Runtime |
| 出演者 | Actresses/cast, preserving order and supporting 50 names |
| 監督 | Directors |
| シリーズ | Series |
| メーカー | Maker |
| レーベル | Label |
| ジャンル | Genres |
| 関連タグ | Related tags |
| 配信品番 | Distribution Product ID |
| メーカー品番 | Manufacturer Product ID |
| 紹介文 | Video introduction/description |

Available fields depend on the product page. The movie title and source URL are also saved.

## Browse the library

- **Table view:** Cover, Release date, Product ID, Actresses, Title, and Maker. Release date uses the streaming release date. Resize columns by dragging their edges, and rearrange them by dragging headers. Click any header except Cover to sort; click again to reverse the order.
- **Cover view:** fixed-size cards with fitted covers, Product ID, streaming release date, title, and cast. Use **Sort by** to choose Title, Release date, Product ID, Actresses or Maker; the arrow button reverses ascending/descending order.
- Search by title, Product ID, actress, maker, or series. Sorting applies across all result pages.
- Both views show **24 movies per page**. Click a page number, use **Previous / Next** to move one page, or enter a page number and press **Enter / Go**. Up to ten numbered buttons are shown at a time.
- Double-click a movie to open its details. **Previous / Next** and the **Left / Right arrow keys** follow the current search and sort order across pages.
- Click the detail cover to open the full-resolution viewer. Covers are centered, preserve their proportions, and do not enlarge beyond their original resolution.
- **Refresh metadata & cover** queues the saved DMM or MGS product URL again. It updates metadata and checks whether the cover needs another download.

## Storage, backups and updates

Default settings in **config.toml**:

```toml
[storage]
data_dir = "data"
library_dir = "library"
```

Relative paths resolve beside config.toml. Use **Database & Library → Add library folder…** to register additional library folders. All libraries share one database.

Close jav-data before moving or backing up its files. Back up **config.toml**, **data**, **library**, and any additional libraries. The data folder contains private session cookies and should not be uploaded to GitHub or shared.

To update safely, extract the new release into a new folder, then copy your existing config.toml, data, and library into it before starting. Keep additional libraries at their configured locations. Moving to another Windows account or computer may require signing in to the source websites again.

## Troubleshooting

| Problem | What to check |
|---|---|
| DMM/MGS cannot open or products are unavailable | Confirm your Japan IP applies to jav-data and that the product is accessible in its embedded browser. |
| Search says authentication is required | Select the matching website in Website Authentication, complete confirmation/login, then mark the session ready. |
| Scraping waits for a session | Repeat authentication, then retry the affected job. |
| A cover fails | Check connectivity and the selected website session, resume downloads if paused, then retry. |
| The executable will not start after moving it | Extract/copy the entire folder, including _internal; use a writable location. |
| A website layout change breaks parsing | Save the affected product URL and report the problem without sharing cookies or account information. |

## Develop and build from source

The source uses Python 3.12+, PySide6/Qt WebEngine, FastAPI, SQLAlchemy/SQLite, Beautiful Soup, Pillow, and Alembic. PyInstaller produces the standalone Windows folder.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m jav_data.desktop
```

Checks:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests
```

For a reproducible Windows environment, install **requirements.lock.txt**, then install the project with `pip install --no-deps -e .`.

Close the destination application before building. An ordinary build preserves the existing portable library and configuration:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build-portable.ps1
```

A separate clean build requires a new output directory:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build-portable.ps1 -OutputDirectory "portable\release-clean\jav-data" -Fresh
```

The source repository excludes databases, personal configuration, cookies, downloaded media, virtual environments, and build outputs. See [portable details](docs/portable-desktop.md) and the [performance review](docs/performance-review.md).

To archive a fresh release folder with documentation, dependency notices, a manifest, and a checksum:

```powershell
.\.venv\Scripts\python.exe scripts/package-release.py --folder "portable\release-clean\jav-data" --version 1.0
```

Third-party license notices are included in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and docs/third-party.
