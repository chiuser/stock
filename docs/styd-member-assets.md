# STYD member asset pull workflow

This document standardizes the one-off STYD member CSV and face-image pulls.
Generated CSV files and image directories are ignored by git because they may
contain private member data.

## 1. Prepare Chrome DevTools

Detail-page face pulls require an already logged-in Chrome launched with a
DevTools port. Recent Chrome versions also require a non-default user data dir.

```bash
osascript -e 'tell application "Google Chrome" to quit'
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --remote-allow-origins='*' \
  --user-data-dir=/tmp/styd-chrome-debug-profile-run \
  --no-first-run \
  --no-default-browser-check \
  "https://pro.styd.cn/shop/member/list/useful?app_brand_id=2155116073975893&app_shop_id=2179180977014260&current_page=1"
```

Log in in that Chrome window before running DevTools commands.

## 2. Incremental member sync

Use `incremental-sync` for normal repeated pulls. It scrapes the filtered member
list through DevTools, compares the result with a canonical local CSV by `id`,
appends new member rows, and downloads images only for new IDs or missing local
image files.

```bash
python scripts/styd_member_assets.py incremental-sync \
  --list-url "https://pro.styd.cn/shop/member/list/useful?app_brand_id=2155116073975893&app_shop_id=2179180977014260&keyword=&member_level=2&follow_salesman_id=-1&follow_coach_id=-1&follow_status=-1&tag_id=-1&buy_personal_course=-1&current_page=1&has_face=-1&has_physical=-1&has_finger=-1&register_way=-1&vip_level_id=-1&_f=6" \
  --master-csv styd_members_master.csv \
  --faces-dir styd_member_faces \
  --full-faces-dir styd_member_faces_full
```

Outputs:

- `styd_members_master.csv`: canonical member CSV, appended by new `id`.
- `styd_member_faces/<id>.jpg`: detail-page `biz-face-upload__face` images.
- `styd_member_faces_full/<id>.jpg`: larger images from `avatar_full_url`.
- `styd_member_sync_runs/<timestamp>/current_members.csv`: list snapshot for this run.
- `styd_member_sync_runs/<timestamp>/new_members.csv`: only the newly discovered members.
- `styd_member_sync_runs/<timestamp>/sync_summary.json`: counts and paths for the run.

When the canonical CSV filename contains a trusted row count suffix such as
`existing_faces_252.csv`, rename it after a successful non-dry-run sync so the
suffix matches the verified unique-ID count. Keep the run directory intact as
the audit trail, and update any run metadata that stores the canonical CSV path
if the file is renamed after the script finishes.

Useful options:

```bash
--dry-run
--max-pages 1
--no-fill-missing-existing
--refresh-existing
--skip-detail-faces
--skip-avatar-full
```

## 3. Refresh one member

Use `refresh-member` when a specific member's CSV row or images need to be
fixed. It first finds the member in the filtered list by `id`, updates that row
in the canonical CSV, then downloads the latest `avatar_full_url` image and the
detail-page `biz-face-upload__face` image.

```bash
python scripts/styd_member_assets.py refresh-member \
  --member-id 3787108955784829 \
  --list-url "https://pro.styd.cn/shop/member/list/useful?app_brand_id=2155116073975893&app_shop_id=2179180977014260&keyword=&member_level=2&follow_salesman_id=-1&follow_coach_id=-1&follow_status=-1&tag_id=-1&buy_personal_course=-1&current_page=1&has_face=-1&has_physical=-1&has_finger=-1&register_way=-1&vip_level_id=-1&_f=6" \
  --master-csv styd_members_master.csv \
  --faces-dir styd_member_faces \
  --full-faces-dir styd_member_faces_full
```

By default this command overwrites existing images because it is intended as a
repair/update operation. Use `--no-force` if you only want to fill missing files.

Outputs are written under `styd_member_sync_runs/refresh_<id>_<timestamp>/`,
including `member_row.csv`, `master_before.csv`, two download reports, and
`refresh_summary.json`.

Useful options:

```bash
--dry-run
--no-force
--max-pages 1
--skip-detail-faces
--skip-avatar-full
```

## 4. Download detail-page face images

This opens each member detail page and downloads `img.biz-face-upload__face`.
Existing `<id>.jpg` files are skipped by default.

```bash
python scripts/styd_member_assets.py download-detail-faces \
  --member-csv styd_members_20260630_002401.csv \
  --output-dir styd_member_faces
```

Useful options:

```bash
--app-brand-id 2155116073975893
--app-shop-id 2179180977014260
--cdp-url http://127.0.0.1:9222
--limit 10
--no-skip-existing
```

The command writes `_download_report.csv` and `_download_report.json` inside the
output directory.

## 5. Filter member rows by a face directory

Use this to produce a member CSV corresponding to a directory of `<id>.jpg`
files.

```bash
python scripts/styd_member_assets.py filter-by-faces \
  --member-csv styd_members_20260630_002401.csv \
  --faces-dir styd_member_faces \
  --output-csv styd_members_20260630_002401_existing_faces_221.csv
```

## 6. Download `avatar_full_url` images

This reads the `avatar_full_url` column from a member CSV and downloads the
larger image into `<id>.jpg`.

```bash
python scripts/styd_member_assets.py download-avatar-full \
  --member-csv styd_members_20260630_002401_existing_faces_221.csv \
  --output-dir styd_member_faces_full
```

## 7. Split a suspicious batch by file mtime

This copies or moves files newer than a cutoff into a separate directory and
writes a matching report in the destination.

```bash
python scripts/styd_member_assets.py split-by-mtime \
  --source-dir styd_member_faces \
  --dest-dir styd_member_faces_new_20260630_178 \
  --cutoff "2026-06-30 00:00:00" \
  --expected-count 178 \
  --move
```

## 8. Summarize current files

```bash
python scripts/styd_member_assets.py summary
```

The summary reports row counts, unique IDs, image counts, byte totals, and
download report status counts.

## 9. Prune by trusted small-face directory

When the curated `styd_member_faces/` directory is manually cleaned, treat the
remaining `<id>.jpg` files as the trusted ID set. Before pruning, create a run
directory and copy the current master CSV plus both `_download_report` files
into it. Then:

- remove master CSV rows whose `id` no longer has a matching small-face file;
- remove the corresponding `<id>.jpg` files from `styd_member_faces_full/`;
- rewrite both small-face and full-face `_download_report.csv/json` files so
  they contain only trusted IDs;
- rename a count-suffixed master CSV so the suffix matches the verified unique
  ID count.

Prefer moving removed full-face images into the run directory instead of using a
permanent delete, so the cleanup can be rolled back if the trusted small-face
set was wrong.

## 10. Build teacher and staff face CSV files

Coach and staff face images can be staged in local `teacher/` and `staff/`
directories. Generate `teacher.csv` and `staff.csv` from the actual files in
those directories with these columns:

- `ID`
- `姓名`
- `人脸图片名称`

For normal files named `<numeric-id>_<name>.<ext>`, split at the first
underscore. Ignore non-image files such as `.DS_Store`. If a file does not
match the normal numeric-id format, keep it in the CSV with an empty `ID` and
the filename stem as `姓名` so no staged face file silently disappears.

The `teacher/`, `staff/`, `teacher.csv`, and `staff.csv` paths contain local
private face assets and derived personnel data. Keep them ignored by git.

## 11. P6S named image copies

### Technical plan

Goal: every newly added or refreshed person should have both the original
image file and a P6S-importable named copy. For members this applies to the
small detail image and the `avatar_full_url` image. For coaches and staff this
applies to their local staged image directories.

Scope:

- keep the existing source-of-truth files unchanged, such as
  `styd_member_faces/<id>.jpg`, `styd_member_faces_full/<id>.jpg`,
  `teacher/<id>_<name>.<ext>`, and `staff/<id>_<name>.<ext>`;
- generate named copies under sibling `*_p6s_named` directories;
- use the same member CSV row that drives downloads so the display name and ID
  stay aligned with the source image;
- update run reports so a partial run can be audited.

Impact:

- `incremental-sync` and `refresh-member` generate member P6S named copies by
  default after the relevant source image exists;
- standalone regeneration is available for members, coaches, or staff when a
  local directory needs to be rebuilt;
- generated P6S files remain ignored by git through the existing
  `styd_member_faces*/`, `teacher_p6s_named/`, and `staff_p6s_named/` rules.

Risks:

- if a name changes, the old P6S-named copy can become stale;
- if a name contains path separators or `#`, it can break the P6S filename
  structure;
- if an image download fails, the named copy should not be created from an
  empty or missing source file.

Rollback:

- source CSVs and source image files are not modified by P6S copy generation;
- remove the affected file in the `*_p6s_named` directory and rerun the command;
- use the run directory reports and `master_before.csv` for member CSV rollback
  when a refresh or incremental sync also changed the master CSV.

Verification:

- confirm the source image exists and is non-empty;
- confirm the named target exists and matches the source byte size;
- confirm the target filename matches `I<name>#S0#T2#M<id>.<ext>`;
- run `python scripts/styd_member_assets.py summary` and inspect the relevant
  source and named directories.

### LLD

Filename contract:

```text
I<display-name>#S0#T2#M<stable-id>.<source-extension>
```

The `I` prefix, `#S0#T2` segment, and `#M` ID marker are fixed. The display
name comes from the CSV row. For members prefer `nickname`, then
`member_name`, then `id`. For coaches and staff use the `姓名` column. The
source extension is preserved, so `.jpg`, `.jpeg`, and `.png` remain distinct.

Module boundaries:

- source image download remains handled by `download-detail-faces`,
  `download-avatar-full`, `incremental-sync`, and `refresh-member`;
- P6S named-copy generation is a local filesystem operation that copies an
  already downloaded source image;
- CSV parsing and report writing reuse the existing helper functions in
  `scripts/styd_member_assets.py`.

Interfaces:

- `incremental-sync` accepts optional `--faces-p6s-named-dir`,
  `--full-faces-p6s-named-dir`, and `--skip-p6s-named` arguments;
- `refresh-member` accepts the same arguments and overwrites the target named
  copies when `--force` is enabled;
- `build-p6s-named` rebuilds a named directory from any CSV and source image
  directory, with configurable ID, name, and image filename columns.

Data flow:

1. scrape or read the CSV row;
2. ensure the source image exists in the relevant source directory;
3. build the P6S filename from the CSV name and stable ID;
4. copy the image into the `*_p6s_named` directory;
5. remove stale named copies for the same ID when the display name changed;
6. write per-run P6S named-copy reports.

Exception handling:

- missing ID, missing name, or missing source image is recorded as a failed row
  instead of silently producing an invalid file;
- stale copies are only removed after the new target file has been written;
- dry runs never create or remove P6S named files.

Deployment and usage:

```bash
python scripts/styd_member_assets.py build-p6s-named \
  --source-csv styd_members_20260703_existing_faces_245.csv \
  --source-dir styd_member_faces_full \
  --output-dir styd_member_faces_full_p6s_named \
  --id-column id \
  --name-column nickname \
  --fallback-name-column member_name
```

For coaches or staff:

```bash
python scripts/styd_member_assets.py build-p6s-named \
  --source-csv teacher.csv \
  --source-dir teacher \
  --output-dir teacher_p6s_named \
  --id-column ID \
  --name-column 姓名 \
  --image-column 人脸图片名称
```
