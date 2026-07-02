# P6SCGI ShowDoc Offline Mirror LLD

## Module Boundary

The sync module is a standalone command-line script:

- Input: public ShowDoc item ID and server URL.
- Output: local Markdown files and a JSON manifest.
- No dependency on FastAPI app modules.
- No access to camera hardware or local secrets.

## Command

```bash
python3 scripts/sync_p6scgi_showdoc.py \
  --output docs/p6scgi-showdoc \
  --delay 0.35 \
  --retries 3
```

## Configuration

Default values are hard-coded for this public documentation mirror:

- `item_id`: `663863654`
- `server`: `http://p6scgi-api.p6sai.com:4999/server/index.php?s=`
- `web_base`: `http://p6scgi-api.p6sai.com:4999/web/#`
- `output`: `docs/p6scgi-showdoc`
- `delay`: `0.35` seconds per page request
- `timeout`: `20` seconds
- `retries`: `3`

No `.env.local` entry is required because this mirror uses public ShowDoc pages
only.

## Data Flow

1. Call `/api/item/info` with `item_id` to get the item metadata and menu tree.
2. Walk `menu.pages` and nested `menu.catalogs` recursively.
3. For every page, call `/api/page/info` with `item_id` and `page_id`.
4. Decode HTML entities from `page_content`.
5. Create directories matching the catalog path.
6. Write one Markdown file for each page.
7. Write `manifest.json` with all generated files and source metadata.
8. Write `README.md` explaining how to search the mirror.

## Directory Mapping

Each ShowDoc catalog maps to one directory. Each page maps to one Markdown file
inside its catalog directory.

Example:

```text
docs/p6scgi-showdoc/
  01 API/
    智能事件配置管理/
      人脸相关配置管理接口/
        脸库配置管理/
          人员管理/
            增加和更新人员信息以及图片信息__149227016.md
```

## File Naming

Filename rules:

- Strip leading/trailing whitespace.
- Replace `/`, `:`, `*`, `?`, `"`, `<`, `>`, `|`, and control characters with `_`.
- Collapse repeated whitespace.
- Limit long names to a safe length.
- Always append `__{page_id}` to avoid duplicate-title collisions.

## Markdown Format

Each generated file starts with a small metadata block:

```markdown
<!--
source: P6SCGI ShowDoc
item_id: 663863654
page_id: 149227016
source_url: http://p6scgi-api.p6sai.com:4999/web/#/663863654/149227016
catalog_path: 01 API / ...
-->

# 增加和更新人员信息以及图片信息

...
```

The rest of the body keeps the ShowDoc Markdown content as-is after HTML entity
decoding.

## Error Handling

- Network failures are retried with exponential backoff.
- A failed page is recorded in `manifest.json` under `errors`.
- The script continues fetching remaining pages after one page fails.
- The final process exits with code `1` if any page failed.

## Rate Limiting

- Sleep for `delay` seconds after each page request.
- Sleep after transient failures before retrying.
- Use a clear User-Agent so the traffic is identifiable as a local documentation
  mirror.

## Verification

After sync:

- Print item name, catalog count, page count, generated count, failed count.
- Verify generated Markdown count equals successful page count.
- Verify the known page `149227016` contains
  `POST /FaceGroup/UpdatePersonInfoAndFaceImage`.
*** End Patch
