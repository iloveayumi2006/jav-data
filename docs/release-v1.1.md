# jav-data-v1.1

Windows portable release; application version 1.1.0.

## Changes since v1.0

- Cover view is now the default Library view. Table selection uses a pale rose row highlight with a red marker.
- Product URL search shows progress during crawling, then displays all unique URLs sorted A–Z in one scrollable list. The page layout remains the same before, during and after searching.
- Select unwanted URLs and use Delete selected or the Delete key. Copy all URLs and Save all URLs use only the remaining list.
- Removed the 100-URL paste limit. Large queue submissions use grouped lookups and bulk insertion, while scraping remains sequential. Duplicate active jobs are reused.
- Smaller Retry buttons in both scraping and cover-download tables.
- Export metadata at the bottom-right of Library saves all matching movies across every page in the current sort order as an Excel workbook. Japanese values and leading-zero IDs are preserved.
- Pagination is centered on the same row as Export metadata. Removed Open selected movie; double-click still opens movie details.

## Download and requirements

Download jav-data-v1.1-windows-x64.zip, extract the entire folder, and open jav-data.exe. Keep _internal beside it. Python, Qt and the browser runtime are bundled; no separate browser or downloader installation is needed.

Requires Windows 10/11 x64 and a Japan IP connection that covers the app and downloads. A browser-only VPN extension is insufficient. Complete age confirmation and any required account login in Website Authentication. A DMM account is required for products needing sign-in.

## Clean package and updating

The ZIP contains no personal database, cookies, account session, downloaded products or history. First launch creates an empty database and browser profile. README.md, third-party notices and a release manifest are included; SHA256SUMS.txt verifies the download.

To upgrade, close jav-data and back up config.toml, data and all libraries. Extract v1.1 into a new folder, then copy your configuration, data and default library into it before opening the app. Keep additional libraries at their configured paths.
