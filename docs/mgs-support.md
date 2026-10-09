# MGS support

Implemented on `codex/mgs-support`. The published v0.1.0 release remains the DMM-only baseline. No database migration is needed, and application updates preserve the existing configuration and collection.

## Workflow

Connect a Japan VPN, open **Website Authentication**, choose **MGS**, and complete age confirmation and any required login in the embedded browser. Mark the session ready. Select MGS in **Search Product URLs**, collect the results, then copy batches of up to 100 URLs into **Scraping & Downloads**. Pasted DMM and MGS URLs are recognized automatically. Authentication uses one browser profile with domain-scoped cookies; the close button pauses the shared scraping queue.

The original MGS ID is retained as manufacturer product ID. Distribution IDs use lowercase letters and numbers padded to at least five digits: ABF-232 becomes abf00232. Libraries, cover names, and automatic Emby NFO follow the existing workflow. Covers use the page's enlarged-image link. Introduction text uses the full page description metadata rather than the shortened visible preview.

IDs with numeric prefixes or extra suffixes are currently unsupported and rejected explicitly. A conflicting distribution ID from another website, or from another original MGS identifier, fails before changing existing movie metadata or files. Repeated scrapes of the same MGS URL update the original movie and retain its storage location.

## Validation

- Live products: ABF-232, ABW-054, ABP-542.
- QtWebEngine navigation, DOM extraction, generated IDs, Japanese fields and complete introductions verified against all three.
- Enlarged covers downloaded through the actual download worker: 840 × 566 pixels for each sample.
- metadata.json, distribution-ID-fanart.jpg and movie.nfo created in temporary storage; validation data removed afterward.
- Live actress keyword search collected 150 unique URLs across two source pages; displayed in batches of 100 and 50, sorted A–Z.
- All 72 automated tests passed. Automated coverage includes DMM regression, URL/ID validation, source and original-ID collisions, repeat scraping, cover matching, cookie scoping, full descriptions, search filters and pagination, and native desktop/browser startup.

## Rollback

Switch source back to tag `v0.1.0` or use its published portable ZIP. Keep matching backups of config.toml, data and every configured library folder before testing any new build against personal data. Git does not back up those ignored folders. This implementation makes no schema changes but can add new movie records and files when used against a live library.
