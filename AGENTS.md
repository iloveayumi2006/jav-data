# Local development workflow

- After application changes, run the relevant checks and update the local portable build at `portable/jav-data` before considering the work complete.
- Build and verify a staged copy first. Preserve the existing configuration, database, browser session, and library files when updating the local portable app.
- If the app is running, finish staging and verification before asking the user to close it for replacement.
- Updating the local portable build does not authorize publishing a GitHub release or uploading files.
