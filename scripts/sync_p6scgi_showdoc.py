#!/usr/bin/env python3
"""Mirror the public P6SCGI ShowDoc project into local Markdown files."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_ITEM_ID = "663863654"
DEFAULT_SERVER = "http://p6scgi-api.p6sai.com:4999/server/index.php?s="
DEFAULT_WEB_BASE = "http://p6scgi-api.p6sai.com:4999/web/#"
DEFAULT_OUTPUT = "docs/p6scgi-showdoc"
USER_AGENT = "stock-local-showdoc-mirror/1.0"


@dataclass(frozen=True)
class PageRef:
    page_id: str
    title: str
    catalog_path: tuple[str, ...]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mirror the public P6SCGI ShowDoc project into Markdown.",
    )
    parser.add_argument("--item-id", default=DEFAULT_ITEM_ID)
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--web-base", default=DEFAULT_WEB_BASE)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--delay",
        type=float,
        default=0.35,
        help="Seconds to sleep after each page request.",
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--retries", type=int, default=3)
    return parser.parse_args()


def api_post(
    server: str,
    api_path: str,
    payload: dict[str, Any],
    timeout: float,
    retries: int,
) -> dict[str, Any]:
    url = f"{server}{api_path}"
    data = urllib.parse.urlencode(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": USER_AGENT,
    }
    last_error: Exception | None = None

    for attempt in range(retries + 1):
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
            parsed = json.loads(raw)
            if parsed.get("error_code") != 0:
                raise RuntimeError(
                    f"ShowDoc API error {parsed.get('error_code')}: "
                    f"{parsed.get('error_message')}"
                )
            return parsed
        except (
            TimeoutError,
            urllib.error.URLError,
            urllib.error.HTTPError,
            json.JSONDecodeError,
            RuntimeError,
        ) as exc:
            last_error = exc
            if attempt >= retries:
                break
            time.sleep(min(2**attempt, 8))

    raise RuntimeError(f"POST {api_path} failed after {retries + 1} attempts: {last_error}")


def collect_pages(menu: dict[str, Any]) -> tuple[list[PageRef], int]:
    pages: list[PageRef] = []
    catalog_count = 0

    def add_pages(raw_pages: list[dict[str, Any]], catalog_path: tuple[str, ...]) -> None:
        for page in raw_pages:
            pages.append(
                PageRef(
                    page_id=str(page["page_id"]),
                    title=str(page["page_title"]),
                    catalog_path=catalog_path,
                )
            )

    def walk(catalogs: list[dict[str, Any]], parent_path: tuple[str, ...]) -> None:
        nonlocal catalog_count
        used_names: set[str] = set()
        for catalog in catalogs:
            catalog_count += 1
            raw_name = str(catalog.get("cat_name") or f"catalog_{catalog['cat_id']}")
            name = sanitize_path_component(raw_name) or f"catalog_{catalog['cat_id']}"
            if name in used_names:
                name = f"{name}__{catalog['cat_id']}"
            used_names.add(name)
            next_path = (*parent_path, name)
            add_pages(catalog.get("pages") or [], next_path)
            walk(catalog.get("catalogs") or [], next_path)

    add_pages(menu.get("pages") or [], tuple())
    walk(menu.get("catalogs") or [], tuple())
    return pages, catalog_count


def sanitize_path_component(value: str, max_length: int = 120) -> str:
    value = html.unescape(value)
    value = re.sub(r"[\x00-\x1f]", "_", value)
    value = re.sub(r'[\\/:*?"<>|]', "_", value)
    value = re.sub(r"\s+", " ", value).strip()
    value = value.strip(". ")
    if not value:
        return ""
    return value[:max_length].rstrip(". ")


def page_filename(title: str, page_id: str) -> str:
    safe_title = sanitize_path_component(title, max_length=100) or "untitled"
    return f"{safe_title}__{page_id}.md"


def source_url(web_base: str, item_id: str, page_id: str) -> str:
    return f"{web_base}/{item_id}/{page_id}"


def render_markdown(
    item_id: str,
    item_name: str,
    page: dict[str, Any],
    page_ref: PageRef,
    web_base: str,
) -> str:
    content = html.unescape(str(page.get("page_content") or "")).strip()
    title = str(page.get("page_title") or page_ref.title)
    catalog_path = " / ".join(page_ref.catalog_path)
    url = source_url(web_base, item_id, page_ref.page_id)
    metadata = [
        "<!--",
        "source: P6SCGI ShowDoc",
        f"item_name: {item_name}",
        f"item_id: {item_id}",
        f"page_id: {page_ref.page_id}",
        f"source_url: {url}",
        f"catalog_path: {catalog_path}",
        "-->",
        "",
        f"# {title}",
        "",
    ]
    return "\n".join(metadata) + content + "\n"


def write_readme(output_dir: Path, item_name: str, page_count: int) -> None:
    readme = f"""# P6SCGI ShowDoc Offline Mirror

This directory is generated from the public ShowDoc project `{item_name}`.

- Pages: {page_count}
- Source: {DEFAULT_WEB_BASE}/{DEFAULT_ITEM_ID}
- Generated files: one Markdown file per ShowDoc page.

Search examples:

```bash
rg "UpdatePersonInfoAndFaceImage" docs/p6scgi-showdoc
rg "FaceUUID" docs/p6scgi-showdoc
rg "QueryPersonInfoListCount" docs/p6scgi-showdoc
```

Regenerate:

```bash
python3 scripts/sync_p6scgi_showdoc.py --output docs/p6scgi-showdoc --delay 0.35
```
"""
    (output_dir / "README.md").write_text(readme, encoding="utf-8")


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    item_response = api_post(
        args.server,
        "/api/item/info",
        {"item_id": args.item_id},
        args.timeout,
        args.retries,
    )
    item = item_response["data"]
    item_name = str(item.get("item_name") or args.item_id)
    pages, catalog_count = collect_pages(item["menu"])

    manifest: dict[str, Any] = {
        "source": "P6SCGI ShowDoc",
        "item_id": args.item_id,
        "item_name": item_name,
        "catalog_count": catalog_count,
        "page_count": len(pages),
        "generated": [],
        "errors": [],
    }

    print(f"Item: {item_name}")
    print(f"Catalogs: {catalog_count}")
    print(f"Pages: {len(pages)}")

    for index, page_ref in enumerate(pages, start=1):
        try:
            page_response = api_post(
                args.server,
                "/api/page/info",
                {"item_id": args.item_id, "page_id": page_ref.page_id},
                args.timeout,
                args.retries,
            )
            page = page_response["data"]
            relative_dir = Path(*page_ref.catalog_path) if page_ref.catalog_path else Path()
            target_dir = output_dir / relative_dir
            target_dir.mkdir(parents=True, exist_ok=True)
            target_path = target_dir / page_filename(page_ref.title, page_ref.page_id)
            target_path.write_text(
                render_markdown(args.item_id, item_name, page, page_ref, args.web_base),
                encoding="utf-8",
            )
            manifest["generated"].append(
                {
                    "page_id": page_ref.page_id,
                    "title": page_ref.title,
                    "catalog_path": list(page_ref.catalog_path),
                    "file": str(target_path.relative_to(output_dir)),
                    "source_url": source_url(args.web_base, args.item_id, page_ref.page_id),
                }
            )
            if index % 25 == 0 or index == len(pages):
                print(f"Fetched {index}/{len(pages)} pages")
        except Exception as exc:  # Keep the mirror useful even if one page fails.
            manifest["errors"].append(
                {
                    "page_id": page_ref.page_id,
                    "title": page_ref.title,
                    "catalog_path": list(page_ref.catalog_path),
                    "error": str(exc),
                }
            )
            print(f"ERROR page {page_ref.page_id}: {exc}", file=sys.stderr)
        finally:
            time.sleep(max(args.delay, 0.0))

    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_readme(output_dir, item_name, len(pages))

    print(f"Generated: {len(manifest['generated'])}")
    print(f"Errors: {len(manifest['errors'])}")
    print(f"Output: {output_dir}")
    return 1 if manifest["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
