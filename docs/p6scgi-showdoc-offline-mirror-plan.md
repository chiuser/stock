# P6SCGI ShowDoc Offline Mirror Technical Plan

## Goal

Mirror the public P6SCGI ShowDoc project into local Markdown files so the repo
can be searched with normal filesystem tools such as `rg` and Finder. The local
mirror should preserve the ShowDoc folder hierarchy: each ShowDoc catalog
becomes a directory, and each ShowDoc page becomes one `.md` file.

## Scope

- Source project: `http://p6scgi-api.p6sai.com:4999/web/#/663863654/149227016`
- Source API: `http://p6scgi-api.p6sai.com:4999/server/index.php?s=`
- Local output: `docs/p6scgi-showdoc/`
- Script: `scripts/sync_p6scgi_showdoc.py`
- Output format: Markdown plus small metadata comments at the top of each file.
- Refresh behavior: safe to rerun; unchanged pages can be overwritten with the
  same content.

Out of scope:

- No local web UI.
- No database, vector index, or embedding pipeline.
- No private credentials, camera credentials, or local `.env.local` values.
- No modification of camera runtime code.

## Impact

- Adds a local documentation mirror under `docs/p6scgi-showdoc/`.
- Adds one sync script under `scripts/`.
- Does not change application runtime behavior.
- Does not call the camera at `192.168.1.61`.

## Risks

- The ShowDoc server may throttle or block if requests are too frequent.
- Page titles and catalog names may contain characters that are invalid or
  awkward as local filenames.
- Duplicate page titles under one directory may overwrite each other if not
  handled.
- ShowDoc content may include HTML entities that need to be decoded for readable
  Markdown.
- The generated mirror may be large, so Git tracking should be decided after the
  first sync size is known.

## Risk Controls

- Use a default delay between page downloads.
- Add retry with exponential backoff for transient HTTP failures.
- Sanitize path names and append page IDs when needed to avoid collisions.
- Write one `manifest.json` with page ID, title, path, and source URL so files
  can be traced back to ShowDoc.
- Keep generated Markdown as plain files for cheap local search.

## Rollback

- Remove the generated mirror directory: `docs/p6scgi-showdoc/`.
- Remove the sync script: `scripts/sync_p6scgi_showdoc.py`.
- No runtime config or database rollback is needed.

## Verification

- Fetch project metadata and confirm the item name is `P6SCGI API（CN）`.
- Count catalogs and pages from the ShowDoc menu.
- Generate one Markdown file per ShowDoc page.
- Confirm `manifest.json` page count matches the generated Markdown count.
- Spot-check the known page `149227016` exists and contains
  `POST /FaceGroup/UpdatePersonInfoAndFaceImage`.
- Confirm file search works with `rg "UpdatePersonInfoAndFaceImage" docs/p6scgi-showdoc`.
