# jav-data-v1.2

Windows portable release; application version 1.2.0.

## Changes since v1.1

- Authentication displays the embedded browser while the website loads. Navigation now honors document readiness instead of waiting for every page resource.
- Background search and scraping pages skip web images, media, fonts, prefetches and favicons while preserving scripts and API requests. Original cover downloads remain separate.
- Hidden authentication pages pause when Chromium considers it safe and resume when shown. Cookies and login state persist.
- Scraping and cover workers fetch only the next queued record, reducing temporary memory use on large queues.
- Progress tables reuse unchanged rows and Retry controls. Cover-download history shows all uncleared entries beyond 200.
- Fixed navigation replacement, timeout recovery and consecutive loads while an earlier page still has pending resources.
- Portable packaging includes Python's matching OpenSSL libraries and required certificate-policy resource, with TLS verification enabled.

Offline synthetic tests measured next-task selection among 20,000 queued scrapes at about 203 ms before and 0.22 ms after, and one cover progress update among 10,000 rows at about 210 ms before and 5.6 ms after. These are individual local operations, not live website speed guarantees. See the included performance review for details.

## Download and requirements

Download **jav-data-v1.2-windows-x64.zip**, extract the entire folder and open **jav-data.exe**. Keep **_internal** beside it. Python, Qt and the embedded browser are bundled.

Requires Windows 10/11 x64 and a Japan IP connection covering the app and downloads. Connect your Japan VPN before Website Authentication. Complete age confirmation and any required account login; a DMM account is needed for products requiring sign-in.

## Clean package and upgrading

The package contains no personal database, library contents, cookies, saved account session or history. First launch creates a new database and browser profile. README, documentation, third-party notices and a file manifest are included; SHA256SUMS.txt verifies the ZIP.

To upgrade, close jav-data and back up your configuration, data and libraries. Extract v1.2 into a new folder, then copy config.toml, data and the default library from your previous portable folder before opening it. Keep additional libraries at their configured paths.
