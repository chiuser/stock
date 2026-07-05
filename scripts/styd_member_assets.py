"""Standard utilities for STYD member CSV exports and face images.

The script intentionally keeps credentials out of the repository. Browser-only
pages are read through an already logged-in Chrome DevTools session, while
signed image URLs from exported CSV files are downloaded directly.
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_APP_BRAND_ID = os.environ.get("STYD_APP_BRAND_ID", "2155116073975893")
DEFAULT_APP_SHOP_ID = os.environ.get("STYD_APP_SHOP_ID", "2179180977014260")
DEFAULT_CDP_URL = os.environ.get("STYD_CDP_URL", "http://127.0.0.1:9222")
DEFAULT_FACE_SELECTOR = "img.biz-face-upload__face, .biz-face-upload__face img"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
REPORT_FIELDS = ["member_id", "status", "file", "bytes", "error", "url"]
P6S_REPORT_FIELDS = [
    "member_id",
    "status",
    "source_file",
    "file",
    "bytes",
    "name",
    "stale_removed",
    "error",
]
MEMBER_FIELDS = [
    "page",
    "id",
    "member_name",
    "phone",
    "nickname",
    "member_level",
    "member_status",
    "member_source",
    "follow_salesman",
    "follow_coach",
    "registered_at",
    "formal_member_date",
    "actual_consumption_yuan",
    "cumulative_refund_yuan",
    "avatar_thumb_url",
    "avatar_full_url",
    "row_text",
]


class StydError(RuntimeError):
    """Expected operational error with a concise message for CLI users."""


def resolve_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def write_csv_rows(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_report_files(csv_path: Path, json_path: Path, rows: list[dict[str, Any]]) -> None:
    write_csv_rows(csv_path, REPORT_FIELDS, rows)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)


def write_report(output_dir: Path, rows: list[dict[str, Any]]) -> None:
    write_report_files(
        output_dir / "_download_report.csv",
        output_dir / "_download_report.json",
        rows,
    )


def write_p6s_report_files(csv_path: Path, json_path: Path, rows: list[dict[str, Any]]) -> None:
    write_csv_rows(csv_path, P6S_REPORT_FIELDS, rows)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)


def merge_report(output_dir: Path, new_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge per-run download rows into an output directory's cumulative report."""
    report_path = output_dir / "_download_report.csv"
    existing_rows: list[dict[str, Any]] = []
    if report_path.exists():
        _, existing_rows = read_csv_rows(report_path)
    ordered_ids = [row.get("member_id", "") for row in existing_rows if row.get("member_id")]
    by_id = {row.get("member_id", ""): row for row in existing_rows if row.get("member_id")}
    for row in new_rows:
        member_id = str(row.get("member_id", ""))
        if not member_id:
            continue
        if member_id not in by_id:
            ordered_ids.append(member_id)
        by_id[member_id] = row
    merged = [by_id[member_id] for member_id in ordered_ids]
    write_report(output_dir, merged)
    return merged


def validate_columns(fieldnames: list[str], required: list[str], csv_path: Path) -> None:
    missing = [name for name in required if name not in fieldnames]
    if missing:
        raise StydError(f"{csv_path} missing required columns: {', '.join(missing)}")


def iter_limited(rows: list[dict[str, str]], limit: int | None) -> list[dict[str, str]]:
    if limit is None:
        return rows
    return rows[:limit]


def is_nonempty_file(path: Path) -> bool:
    return path.exists() and path.is_file() and path.stat().st_size > 0


def is_image_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS


def default_p6s_named_dir(source_dir: Path) -> Path:
    return source_dir.with_name(source_dir.name + "_p6s_named")


def clean_p6s_segment(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[/\\:#\0\r\n\t]+", "", value or "").strip()
    return cleaned or fallback


def p6s_member_id_from_filename(path: Path) -> str:
    stem = path.stem
    if "#M" not in stem:
        return ""
    return stem.rsplit("#M", 1)[1]


def has_p6s_named_file(output_dir: Path, member_id: str) -> bool:
    if not output_dir.exists():
        return False
    return any(
        is_nonempty_file(path) and p6s_member_id_from_filename(path) == member_id
        for path in output_dir.iterdir()
        if is_image_file(path)
    )


def locate_source_image(
    source_dir: Path,
    row: dict[str, str],
    id_column: str,
    image_column: str | None,
) -> Path | None:
    image_name = row.get(image_column or "", "").strip() if image_column else ""
    if image_name:
        candidate = source_dir / image_name
        return candidate if is_nonempty_file(candidate) else None

    member_id = row.get(id_column, "").strip()
    for suffix in sorted(IMAGE_EXTENSIONS):
        candidate = source_dir / f"{member_id}{suffix}"
        if is_nonempty_file(candidate):
            return candidate
    for candidate in source_dir.glob(f"{member_id}.*"):
        if is_image_file(candidate) and is_nonempty_file(candidate):
            return candidate
    return None


def row_display_name(row: dict[str, str], name_columns: list[str], member_id: str) -> str:
    for column in name_columns:
        value = row.get(column, "").strip()
        if value:
            return clean_p6s_segment(value, member_id)
    return member_id


def build_p6s_filename(display_name: str, member_id: str, suffix: str) -> str:
    safe_name = clean_p6s_segment(display_name, member_id)
    safe_id = clean_p6s_segment(member_id, member_id)
    return f"I{safe_name}#S0#T2#M{safe_id}{suffix}"


def matching_p6s_files(output_dir: Path, member_id: str) -> list[Path]:
    if not output_dir.exists():
        return []
    return [
        path
        for path in output_dir.iterdir()
        if is_image_file(path) and p6s_member_id_from_filename(path) == member_id
    ]


def copy_p6s_named_rows(
    rows: list[dict[str, str]],
    source_dir: Path,
    output_dir: Path,
    id_column: str,
    name_columns: list[str],
    image_column: str | None,
    skip_existing: bool,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    target_rows = iter_limited(rows, limit)
    output_dir.mkdir(parents=True, exist_ok=True)
    for index, row in enumerate(target_rows, 1):
        member_id = row.get(id_column, "").strip()
        try:
            if not member_id:
                raise StydError(f"empty {id_column}")
            source_file = locate_source_image(source_dir, row, id_column, image_column)
            if source_file is None:
                raise StydError(f"source image not found in {source_dir}")
            display_name = row_display_name(row, name_columns, member_id)
            target_file = output_dir / build_p6s_filename(display_name, member_id, source_file.suffix)
            stale_files = [path for path in matching_p6s_files(output_dir, member_id) if path != target_file]
            if skip_existing and is_nonempty_file(target_file):
                print(f"[p6s {index}/{len(target_rows)}] skip {member_id} {target_file.name}")
                results.append(
                    {
                        "member_id": member_id,
                        "status": "skipped_existing",
                        "source_file": str(source_file),
                        "file": target_file.name,
                        "bytes": target_file.stat().st_size,
                        "name": display_name,
                        "stale_removed": "",
                        "error": "",
                    }
                )
                continue

            tmp = target_file.with_suffix(target_file.suffix + ".tmp")
            try:
                shutil.copy2(source_file, tmp)
                tmp.replace(target_file)
            finally:
                if tmp.exists():
                    tmp.unlink()
            stale_removed: list[str] = []
            for stale_file in stale_files:
                stale_file.unlink()
                stale_removed.append(stale_file.name)
            print(f"[p6s {index}/{len(target_rows)}] ok {member_id} {target_file.name}")
            results.append(
                {
                    "member_id": member_id,
                    "status": "ok",
                    "source_file": str(source_file),
                    "file": target_file.name,
                    "bytes": target_file.stat().st_size,
                    "name": display_name,
                    "stale_removed": ",".join(stale_removed),
                    "error": "",
                }
            )
        except Exception as exc:  # noqa: BLE001 - keep per-row failures in the report.
            print(f"[p6s {index}/{len(target_rows)}] failed {member_id}: {exc}")
            results.append(
                {
                    "member_id": member_id,
                    "status": "failed",
                    "source_file": "",
                    "file": "",
                    "bytes": 0,
                    "name": "",
                    "stale_removed": "",
                    "error": str(exc)[:500],
                }
            )
    return results


def looks_like_image(data: bytes, content_type: str) -> bool:
    content_type = content_type.lower()
    return (
        "image" in content_type
        or data.startswith(b"\xff\xd8")
        or data.startswith(b"\x89PNG")
        or data.startswith(b"RIFF")
        or data.startswith(b"GIF8")
    )


def download_image(url: str, dest: Path, referer: str = "https://pro.styd.cn/") -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    try:
        if url.startswith("data:"):
            header, payload = url.split(",", 1)
            data = (
                base64.b64decode(payload)
                if ";base64" in header
                else urllib.parse.unquote_to_bytes(payload)
            )
            content_type = header.split(";", 1)[0].replace("data:", "")
        else:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/149.0.0.0 Safari/537.36"
                    ),
                    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                    "Referer": referer,
                },
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                data = response.read()
                content_type = response.headers.get("Content-Type", "")
        if not data:
            raise StydError("downloaded image is empty")
        if not looks_like_image(data, content_type):
            raise StydError(
                f"response does not look like an image: content_type={content_type!r}, bytes={len(data)}"
            )
        tmp.write_bytes(data)
        tmp.replace(dest)
        return len(data)
    finally:
        if tmp.exists():
            tmp.unlink()


def load_page_websocket_url(cdp_url: str, page_url_contains: str) -> str:
    json_url = cdp_url.rstrip("/") + "/json/list"
    with urllib.request.urlopen(json_url, timeout=10) as response:
        tabs = json.load(response)
    pages = [tab for tab in tabs if tab.get("type") == "page"]
    if page_url_contains:
        pages = [tab for tab in pages if page_url_contains in tab.get("url", "")]
    if not pages:
        raise StydError(
            f"no Chrome page found via {json_url}; open/login STYD in the debug Chrome first"
        )
    return pages[0]["webSocketDebuggerUrl"]


class CdpClient:
    def __init__(self, websocket_url: str) -> None:
        try:
            import websocket  # type: ignore[import-not-found]
        except ImportError as exc:
            raise StydError(
                "websocket-client is required for DevTools mode; run `pip install websocket-client`"
            ) from exc
        self._websocket = websocket.create_connection(websocket_url, timeout=30)
        self._next_id = 1

    def close(self) -> None:
        self._websocket.close()

    def call(self, method: str, params: dict[str, Any] | None = None, timeout: int = 30) -> dict[str, Any]:
        call_id = self._next_id
        self._next_id += 1
        self._websocket.settimeout(timeout)
        self._websocket.send(
            json.dumps({"id": call_id, "method": method, "params": params or {}})
        )
        while True:
            message = json.loads(self._websocket.recv())
            if message.get("id") != call_id:
                continue
            if "error" in message:
                raise StydError(f"CDP {method} failed: {message['error']}")
            return message

    def evaluate(self, expression: str) -> dict[str, Any]:
        result = self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
            },
        )
        return result.get("result", {}).get("result", {}).get("value") or {}


def face_extract_expression(selector: str) -> str:
    selector_js = json.dumps(selector)
    return f"""
(() => {{
  const clean = s => (s || '').replace(/\\s+/g, ' ').trim();
  const img = document.querySelector({selector_js});
  const src = img ? (img.currentSrc || img.src || img.dataset?.src || '') : '';
  return {{
    url: location.href,
    title: document.title,
    loggedOut: /登录|account\\/login/.test(document.title + ' ' + location.href),
    bodyHead: clean(document.body?.innerText || '').slice(0, 300),
    hasFace: !!img,
    src,
    className: img ? (img.className || '') : '',
    naturalWidth: img ? img.naturalWidth : 0,
    naturalHeight: img ? img.naturalHeight : 0
  }};
}})()
"""


def build_detail_url_from_options(
    detail_url_template: str | None,
    app_brand_id: str,
    app_shop_id: str,
    member_id: str,
    offset: int,
) -> str:
    if detail_url_template:
        return detail_url_template.format(
            id=urllib.parse.quote(member_id),
            app_brand_id=app_brand_id,
            app_shop_id=app_shop_id,
            f=offset,
        )
    return (
        "https://pro.styd.cn/shop/member/info/reserve"
        f"?id={urllib.parse.quote(member_id)}"
        f"&app_brand_id={app_brand_id}"
        f"&app_shop_id={app_shop_id}"
        f"&_f={offset}"
    )


def build_detail_url(args: argparse.Namespace, member_id: str, offset: int) -> str:
    return build_detail_url_from_options(
        args.detail_url_template,
        args.app_brand_id,
        args.app_shop_id,
        member_id,
        offset,
    )


def wait_for_face(
    client: CdpClient,
    member_id: str,
    selector: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last: dict[str, Any] = {}
    expression = face_extract_expression(selector)
    while time.time() < deadline:
        time.sleep(0.45)
        last = client.evaluate(expression)
        if last.get("loggedOut"):
            raise StydError("Chrome page is logged out; login and retry")
        if member_id in str(last.get("url", "")) and last.get("hasFace") and last.get("src"):
            return last
    raise StydError(f"timed out waiting for face image; last_state={last}")


def member_list_extract_expression() -> str:
    return r"""
(() => {
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const tables = Array.from(document.querySelectorAll('table'));
  const rows = new Map();
  const ensure = id => {
    if (!rows.has(id)) rows.set(id, { id });
    return rows.get(id);
  };

  const main = tables.find(t =>
    Array.from(t.querySelectorAll('thead th')).some(th => clean(th.innerText) === '昵称')
  );
  if (main) {
    for (const tr of main.querySelectorAll('tbody tr[data-row-key]')) {
      const id = tr.dataset.rowKey;
      const cells = Array.from(tr.children).map(td => clean(td.innerText));
      const row = ensure(id);
      Object.assign(row, {
        nickname: cells[2] || '',
        member_level: cells[3] || '',
        member_status: cells[4] || '',
        member_source: cells[5] || '',
        follow_salesman: cells[6] || '',
        follow_coach: cells[7] || '',
        registered_at: cells[8] || '',
        formal_member_date: cells[9] || '',
        actual_consumption_yuan: cells[10] || '',
        cumulative_refund_yuan: cells[11] || '',
        row_text: clean(tr.innerText),
      });
      const img = tr.querySelector('img');
      if (img) {
        row.avatar_thumb_url = img.currentSrc || img.src || '';
        row.avatar_full_url = img.dataset.src || '';
      }
    }
  }

  const left = tables.find(t =>
    Array.from(t.querySelectorAll('thead th')).some(th => clean(th.innerText) === '会员名')
  );
  if (left) {
    for (const tr of left.querySelectorAll('tbody tr[data-row-key]')) {
      const id = tr.dataset.rowKey;
      const cells = Array.from(tr.children).map(td => clean(td.innerText));
      const memberText = cells[1] || '';
      const phoneMatch = memberText.match(/\d{11}/);
      const row = ensure(id);
      row.member_name = phoneMatch ? memberText.replace(phoneMatch[0], '').trim() : memberText;
      row.phone = phoneMatch ? phoneMatch[0] : '';
      const img = tr.querySelector('img');
      if (img) {
        row.avatar_thumb_url = row.avatar_thumb_url || img.currentSrc || img.src || '';
        row.avatar_full_url = row.avatar_full_url || img.dataset.src || '';
      }
    }
  }

  const totalText = clean(document.body.innerText).match(/共\s*(\d+)\s*条/);
  const pageSizeText = clean(document.body.innerText).match(/(\d+)\s*条\/页/);
  const activePage = clean(document.querySelector('.ant-pagination-item-active')?.innerText || '');
  const params = new URLSearchParams(location.search);
  const pageFromUrl = params.get('current_page') || '';
  const resultRows = Array.from(rows.values()).map(row => ({
    page: activePage || pageFromUrl,
    id: row.id || '',
    member_name: row.member_name || row.nickname || '',
    phone: row.phone || '',
    nickname: row.nickname || '',
    member_level: row.member_level || '',
    member_status: row.member_status || '',
    member_source: row.member_source || '',
    follow_salesman: row.follow_salesman || '',
    follow_coach: row.follow_coach || '',
    registered_at: row.registered_at || '',
    formal_member_date: row.formal_member_date || '',
    actual_consumption_yuan: row.actual_consumption_yuan || '',
    cumulative_refund_yuan: row.cumulative_refund_yuan || '',
    avatar_thumb_url: row.avatar_thumb_url || '',
    avatar_full_url: row.avatar_full_url || '',
    row_text: row.row_text || '',
  }));
  return {
    url: location.href,
    title: document.title,
    loggedOut: /登录|account\/login/.test(document.title + ' ' + location.href),
    activePage,
    pageFromUrl,
    total: totalText ? Number(totalText[1]) : null,
    pageSize: pageSizeText ? Number(pageSizeText[1]) : 20,
    count: resultRows.length,
    ids: resultRows.map(r => r.id),
    rows: resultRows,
  };
})()
"""


def list_url_for_page(list_url: str, page_no: int, f_seed: int) -> str:
    parsed = urllib.parse.urlsplit(list_url)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    query["current_page"] = [str(page_no)]
    query["_f"] = [str(f_seed + page_no)]
    new_query = urllib.parse.urlencode(query, doseq=True)
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, new_query, parsed.fragment)
    )


def wait_for_member_list_page(
    client: CdpClient,
    page_no: int,
    previous_ids: list[str] | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    expression = member_list_extract_expression()
    last: dict[str, Any] = {}
    while time.time() < deadline:
        time.sleep(0.6)
        last = client.evaluate(expression)
        if last.get("loggedOut"):
            raise StydError("Chrome page is logged out; login and retry")
        ids = list(last.get("ids") or [])
        active = str(last.get("activePage") or last.get("pageFromUrl") or "")
        url_ok = f"current_page={page_no}" in str(last.get("url", ""))
        page_ok = active == str(page_no) or url_ok
        changed = previous_ids is None or ids != previous_ids
        if page_ok and last.get("count", 0) > 0 and changed:
            return last
    raise StydError(f"timed out waiting for list page {page_no}; last_state={last}")


def scrape_member_list(
    client: CdpClient,
    list_url: str,
    wait_seconds: float,
    f_seed: int,
    max_pages: int | None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    client.call("Page.enable")
    client.call("Page.navigate", {"url": list_url_for_page(list_url, 1, f_seed)}, timeout=10)
    first = wait_for_member_list_page(client, 1, previous_ids=None, timeout_seconds=wait_seconds)
    total = int(first.get("total") or 0)
    page_size = int(first.get("pageSize") or 20)
    total_pages = (total + page_size - 1) // page_size if total else 1
    if max_pages is not None:
        total_pages = min(total_pages, max_pages)

    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    previous_ids: list[str] | None = None
    for page_no in range(1, total_pages + 1):
        if page_no == 1:
            data = first
        else:
            client.call(
                "Page.navigate",
                {"url": list_url_for_page(list_url, page_no, f_seed)},
                timeout=10,
            )
            data = wait_for_member_list_page(
                client,
                page_no,
                previous_ids=previous_ids,
                timeout_seconds=wait_seconds,
            )
        page_ids = list(data.get("ids") or [])
        previous_ids = page_ids
        added = 0
        for row in data.get("rows", []):
            member_id = str(row.get("id", ""))
            if member_id and member_id not in seen:
                rows.append({field: str(row.get(field, "")) for field in MEMBER_FIELDS})
                seen.add(member_id)
                added += 1
        print(
            f"list page {page_no}/{total_pages}: visible={data.get('count')} added={added} first_id={(page_ids or [''])[0]}"
        )
    return rows, {"total": total, "page_size": page_size, "pages": total_pages}


def find_member_in_list(
    client: CdpClient,
    list_url: str,
    member_id: str,
    wait_seconds: float,
    f_seed: int,
    max_pages: int | None,
) -> tuple[dict[str, str], dict[str, Any]]:
    client.call("Page.enable")
    client.call("Page.navigate", {"url": list_url_for_page(list_url, 1, f_seed)}, timeout=10)
    first = wait_for_member_list_page(client, 1, previous_ids=None, timeout_seconds=wait_seconds)
    total = int(first.get("total") or 0)
    page_size = int(first.get("pageSize") or 20)
    total_pages = (total + page_size - 1) // page_size if total else 1
    if max_pages is not None:
        total_pages = min(total_pages, max_pages)

    previous_ids: list[str] | None = None
    for page_no in range(1, total_pages + 1):
        if page_no == 1:
            data = first
        else:
            client.call(
                "Page.navigate",
                {"url": list_url_for_page(list_url, page_no, f_seed)},
                timeout=10,
            )
            data = wait_for_member_list_page(
                client,
                page_no,
                previous_ids=previous_ids,
                timeout_seconds=wait_seconds,
            )
        page_ids = list(data.get("ids") or [])
        previous_ids = page_ids
        print(
            f"scan page {page_no}/{total_pages}: visible={data.get('count')} first_id={(page_ids or [''])[0]}"
        )
        for row in data.get("rows", []):
            if str(row.get("id", "")) == member_id:
                return (
                    {field: str(row.get(field, "")) for field in MEMBER_FIELDS},
                    {
                        "total": total,
                        "page_size": page_size,
                        "pages_scanned": page_no,
                        "total_pages": total_pages,
                    },
                )
    raise StydError(f"member id {member_id} was not found in the filtered list")


def download_detail_faces_rows(
    rows: list[dict[str, str]],
    output_dir: Path,
    id_column: str,
    client: CdpClient,
    app_brand_id: str,
    app_shop_id: str,
    detail_url_template: str | None,
    face_selector: str,
    wait_seconds: float,
    f_seed: int,
    skip_existing: bool,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for index, row in enumerate(rows, 1):
        member_id = row[id_column].strip()
        dest = output_dir / f"{member_id}.jpg"
        if skip_existing and is_nonempty_file(dest):
            print(f"[detail {index}/{len(rows)}] skip {member_id} bytes={dest.stat().st_size}")
            results.append(
                {
                    "member_id": member_id,
                    "status": "skipped_existing",
                    "file": dest.name,
                    "bytes": dest.stat().st_size,
                    "error": "",
                    "url": "",
                }
            )
            continue
        detail_url = build_detail_url_from_options(
            detail_url_template,
            app_brand_id,
            app_shop_id,
            member_id,
            f_seed + index,
        )
        try:
            client.call("Page.navigate", {"url": detail_url}, timeout=10)
            face = wait_for_face(client, member_id, face_selector, wait_seconds)
            image_url = str(face["src"])
            size = download_image(image_url, dest, referer=detail_url)
            print(f"[detail {index}/{len(rows)}] ok {member_id} bytes={size}")
            results.append(
                {
                    "member_id": member_id,
                    "status": "ok",
                    "file": dest.name,
                    "bytes": size,
                    "error": "",
                    "url": image_url,
                }
            )
        except Exception as exc:  # noqa: BLE001 - keep per-id failures in the report.
            print(f"[detail {index}/{len(rows)}] failed {member_id}: {exc}")
            results.append(
                {
                    "member_id": member_id,
                    "status": "failed",
                    "file": "",
                    "bytes": 0,
                    "error": str(exc)[:500],
                    "url": detail_url,
                }
            )
            if "logged out" in str(exc):
                break
    return results


def download_avatar_full_rows(
    rows: list[dict[str, str]],
    output_dir: Path,
    id_column: str,
    url_column: str,
    skip_existing: bool,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for index, row in enumerate(rows, 1):
        member_id = row[id_column].strip()
        image_url = row.get(url_column, "").strip()
        dest = output_dir / f"{member_id}.jpg"
        if skip_existing and is_nonempty_file(dest):
            print(f"[full {index}/{len(rows)}] skip {member_id} bytes={dest.stat().st_size}")
            results.append(
                {
                    "member_id": member_id,
                    "status": "skipped_existing",
                    "file": dest.name,
                    "bytes": dest.stat().st_size,
                    "error": "",
                    "url": image_url,
                }
            )
            continue
        try:
            if not member_id:
                raise StydError("empty member id")
            if not image_url:
                raise StydError(f"empty {url_column}")
            size = download_image(image_url, dest)
            print(f"[full {index}/{len(rows)}] ok {member_id} bytes={size}")
            results.append(
                {
                    "member_id": member_id,
                    "status": "ok",
                    "file": dest.name,
                    "bytes": size,
                    "error": "",
                    "url": image_url,
                }
            )
        except Exception as exc:  # noqa: BLE001 - keep per-id failures in the report.
            print(f"[full {index}/{len(rows)}] failed {member_id}: {exc}")
            results.append(
                {
                    "member_id": member_id,
                    "status": "failed",
                    "file": "",
                    "bytes": 0,
                    "error": str(exc)[:500],
                    "url": image_url,
                }
            )
    return results


def union_fieldnames(primary: list[str], secondary: list[str]) -> list[str]:
    merged = list(primary)
    for field in secondary:
        if field not in merged:
            merged.append(field)
    return merged


def normalize_row(row: dict[str, Any], fieldnames: list[str]) -> dict[str, str]:
    return {field: str(row.get(field, "")) for field in fieldnames}


def command_download_detail_faces(args: argparse.Namespace) -> None:
    member_csv = resolve_path(args.member_csv)
    output_dir = resolve_path(args.output_dir)
    fieldnames, rows = read_csv_rows(member_csv)
    validate_columns(fieldnames, [args.id_column], member_csv)

    ws_url = load_page_websocket_url(args.cdp_url, args.page_url_contains)
    client = CdpClient(ws_url)
    client.call("Page.enable")

    results: list[dict[str, Any]] = []
    target_rows = iter_limited(rows, args.limit)
    try:
        for index, row in enumerate(target_rows, 1):
            member_id = row[args.id_column].strip()
            if not member_id:
                results.append(
                    {
                        "member_id": "",
                        "status": "failed",
                        "file": "",
                        "bytes": 0,
                        "error": "empty member id",
                        "url": "",
                    }
                )
                continue
            dest = output_dir / f"{member_id}.jpg"
            if args.skip_existing and is_nonempty_file(dest):
                result = {
                    "member_id": member_id,
                    "status": "skipped_existing",
                    "file": dest.name,
                    "bytes": dest.stat().st_size,
                    "error": "",
                    "url": "",
                }
                print(f"[{index}/{len(target_rows)}] skip {member_id} bytes={dest.stat().st_size}")
                results.append(result)
                continue

            detail_url = build_detail_url(args, member_id, args.f_seed + index)
            try:
                client.call("Page.navigate", {"url": detail_url}, timeout=10)
                face = wait_for_face(client, member_id, args.face_selector, args.wait_seconds)
                image_url = str(face["src"])
                size = download_image(image_url, dest, referer=detail_url)
                print(f"[{index}/{len(target_rows)}] ok {member_id} bytes={size}")
                results.append(
                    {
                        "member_id": member_id,
                        "status": "ok",
                        "file": dest.name,
                        "bytes": size,
                        "error": "",
                        "url": image_url,
                    }
                )
            except Exception as exc:  # noqa: BLE001 - keep per-id failures in the report.
                print(f"[{index}/{len(target_rows)}] failed {member_id}: {exc}")
                results.append(
                    {
                        "member_id": member_id,
                        "status": "failed",
                        "file": "",
                        "bytes": 0,
                        "error": str(exc)[:500],
                        "url": detail_url,
                    }
                )
                if "logged out" in str(exc):
                    break
    finally:
        client.close()

    write_report(output_dir, results)
    p6s_results: list[dict[str, Any]] = []
    if args.p6s_named_dir and not args.skip_p6s_named:
        p6s_output_dir = resolve_path(args.p6s_named_dir)
        p6s_results = copy_p6s_named_rows(
            target_rows,
            output_dir,
            p6s_output_dir,
            args.id_column,
            [args.p6s_name_column, *args.p6s_fallback_name_column],
            image_column=None,
            skip_existing=args.skip_existing,
        )
        write_p6s_report_files(
            p6s_output_dir / "_p6s_named_report.csv",
            p6s_output_dir / "_p6s_named_report.json",
            p6s_results,
        )
    ok = sum(1 for result in results if result["status"] in {"ok", "skipped_existing"})
    failed = sum(1 for result in results if result["status"] == "failed")
    print(
        json.dumps(
            {
                "total": len(results),
                "ok_or_existing": ok,
                "failed": failed,
                "p6s_named_total": len(p6s_results),
                "p6s_named_failed": sum(1 for result in p6s_results if result["status"] == "failed"),
            },
            ensure_ascii=False,
        )
    )


def command_download_avatar_full(args: argparse.Namespace) -> None:
    member_csv = resolve_path(args.member_csv)
    output_dir = resolve_path(args.output_dir)
    fieldnames, rows = read_csv_rows(member_csv)
    validate_columns(fieldnames, [args.id_column, args.url_column], member_csv)

    results: list[dict[str, Any]] = []
    target_rows = iter_limited(rows, args.limit)
    for index, row in enumerate(target_rows, 1):
        member_id = row[args.id_column].strip()
        image_url = row[args.url_column].strip()
        dest = output_dir / f"{member_id}.jpg"
        if args.skip_existing and is_nonempty_file(dest):
            print(f"[{index}/{len(target_rows)}] skip {member_id} bytes={dest.stat().st_size}")
            results.append(
                {
                    "member_id": member_id,
                    "status": "skipped_existing",
                    "file": dest.name,
                    "bytes": dest.stat().st_size,
                    "error": "",
                    "url": image_url,
                }
            )
            continue
        try:
            if not member_id:
                raise StydError("empty member id")
            if not image_url:
                raise StydError(f"empty {args.url_column}")
            size = download_image(image_url, dest)
            print(f"[{index}/{len(target_rows)}] ok {member_id} bytes={size}")
            results.append(
                {
                    "member_id": member_id,
                    "status": "ok",
                    "file": dest.name,
                    "bytes": size,
                    "error": "",
                    "url": image_url,
                }
            )
        except Exception as exc:  # noqa: BLE001 - keep per-id failures in the report.
            print(f"[{index}/{len(target_rows)}] failed {member_id}: {exc}")
            results.append(
                {
                    "member_id": member_id,
                    "status": "failed",
                    "file": "",
                    "bytes": 0,
                    "error": str(exc)[:500],
                    "url": image_url,
                }
            )

    write_report(output_dir, results)
    p6s_results: list[dict[str, Any]] = []
    if args.p6s_named_dir and not args.skip_p6s_named:
        p6s_output_dir = resolve_path(args.p6s_named_dir)
        p6s_results = copy_p6s_named_rows(
            target_rows,
            output_dir,
            p6s_output_dir,
            args.id_column,
            [args.p6s_name_column, *args.p6s_fallback_name_column],
            image_column=None,
            skip_existing=args.skip_existing,
        )
        write_p6s_report_files(
            p6s_output_dir / "_p6s_named_report.csv",
            p6s_output_dir / "_p6s_named_report.json",
            p6s_results,
        )
    ok = sum(1 for result in results if result["status"] in {"ok", "skipped_existing"})
    failed = sum(1 for result in results if result["status"] == "failed")
    print(
        json.dumps(
            {
                "total": len(results),
                "ok_or_existing": ok,
                "failed": failed,
                "p6s_named_total": len(p6s_results),
                "p6s_named_failed": sum(1 for result in p6s_results if result["status"] == "failed"),
            },
            ensure_ascii=False,
        )
    )


def command_filter_by_faces(args: argparse.Namespace) -> None:
    member_csv = resolve_path(args.member_csv)
    faces_dir = resolve_path(args.faces_dir)
    output_csv = resolve_path(args.output_csv)
    fieldnames, rows = read_csv_rows(member_csv)
    validate_columns(fieldnames, [args.id_column], member_csv)

    face_ids = {path.stem for path in faces_dir.glob("*.jpg") if is_nonempty_file(path)}
    selected = [row for row in rows if row[args.id_column] in face_ids]
    selected_ids = {row[args.id_column] for row in selected}
    missing_from_csv = sorted(face_ids - selected_ids)
    if missing_from_csv and not args.allow_missing:
        raise StydError(
            "some face ids are not present in the member CSV: "
            + ",".join(missing_from_csv[:20])
        )
    write_csv_rows(output_csv, fieldnames, selected)
    print(
        json.dumps(
            {
                "source_rows": len(rows),
                "face_ids": len(face_ids),
                "selected_rows": len(selected),
                "unique_selected_ids": len(selected_ids),
                "missing_from_csv": len(missing_from_csv),
                "output_csv": str(output_csv),
            },
            ensure_ascii=False,
        )
    )


def report_rows_for_ids(report_path: Path, ids: set[str]) -> list[dict[str, Any]]:
    if not report_path.exists():
        return [
            {"member_id": member_id, "status": "ok", "file": f"{member_id}.jpg", "bytes": "", "error": "", "url": ""}
            for member_id in sorted(ids)
        ]
    fieldnames, rows = read_csv_rows(report_path)
    validate_columns(fieldnames, ["member_id"], report_path)
    by_id = {row["member_id"]: row for row in rows}
    return [
        {
            "member_id": member_id,
            "status": by_id.get(member_id, {}).get("status", "ok"),
            "file": by_id.get(member_id, {}).get("file", f"{member_id}.jpg"),
            "bytes": by_id.get(member_id, {}).get("bytes", ""),
            "error": by_id.get(member_id, {}).get("error", ""),
            "url": by_id.get(member_id, {}).get("url", ""),
        }
        for member_id in sorted(ids)
    ]


def command_split_by_mtime(args: argparse.Namespace) -> None:
    source_dir = resolve_path(args.source_dir)
    dest_dir = resolve_path(args.dest_dir)
    cutoff = datetime.fromisoformat(args.cutoff).timestamp()
    candidates = sorted(
        [path for path in source_dir.glob("*.jpg") if path.stat().st_mtime >= cutoff],
        key=lambda path: path.name,
    )
    if args.expected_count is not None and len(candidates) != args.expected_count:
        raise StydError(
            f"expected {args.expected_count} files after cutoff, found {len(candidates)}"
        )
    if dest_dir.exists() and any(dest_dir.iterdir()) and not args.allow_nonempty_dest:
        raise StydError(f"destination directory is not empty: {dest_dir}")
    dest_dir.mkdir(parents=True, exist_ok=True)

    ids = {path.stem for path in candidates}
    report_rows = report_rows_for_ids(source_dir / "_download_report.csv", ids)
    for source_file in candidates:
        target_file = dest_dir / source_file.name
        if args.move:
            shutil.move(str(source_file), str(target_file))
        else:
            shutil.copy2(source_file, target_file)
    write_report(dest_dir, report_rows)
    print(
        json.dumps(
            {
                "mode": "move" if args.move else "copy",
                "files": len(candidates),
                "source_dir": str(source_dir),
                "dest_dir": str(dest_dir),
            },
            ensure_ascii=False,
        )
    )


def command_incremental_sync(args: argparse.Namespace) -> None:
    master_csv = resolve_path(args.master_csv)
    faces_dir = resolve_path(args.faces_dir)
    full_faces_dir = resolve_path(args.full_faces_dir)
    faces_p6s_named_dir = (
        resolve_path(args.faces_p6s_named_dir)
        if args.faces_p6s_named_dir
        else default_p6s_named_dir(faces_dir)
    )
    full_faces_p6s_named_dir = (
        resolve_path(args.full_faces_p6s_named_dir)
        if args.full_faces_p6s_named_dir
        else default_p6s_named_dir(full_faces_dir)
    )
    run_dir = (
        resolve_path(args.run_dir)
        if args.run_dir
        else PROJECT_ROOT / "styd_member_sync_runs" / datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    run_dir.mkdir(parents=True, exist_ok=True)

    ws_url = load_page_websocket_url(args.cdp_url, args.page_url_contains)
    client = CdpClient(ws_url)
    try:
        current_rows, list_meta = scrape_member_list(
            client,
            args.list_url,
            wait_seconds=args.list_wait_seconds,
            f_seed=args.list_f_seed,
            max_pages=args.max_pages,
        )
        write_csv_rows(run_dir / "current_members.csv", MEMBER_FIELDS, current_rows)

        if master_csv.exists():
            master_fieldnames, master_rows = read_csv_rows(master_csv)
            validate_columns(master_fieldnames, [args.id_column], master_csv)
        else:
            master_fieldnames, master_rows = MEMBER_FIELDS, []
        fieldnames = union_fieldnames(master_fieldnames, MEMBER_FIELDS)

        master_by_id = {
            row[args.id_column].strip(): row
            for row in master_rows
            if row.get(args.id_column, "").strip()
        }
        current_by_id = {
            row[args.id_column].strip(): row
            for row in current_rows
            if row.get(args.id_column, "").strip()
        }
        new_ids = [member_id for member_id in current_by_id if member_id not in master_by_id]
        new_rows = [current_by_id[member_id] for member_id in new_ids]

        merged_rows: list[dict[str, str]] = []
        for row in master_rows:
            member_id = row.get(args.id_column, "").strip()
            if member_id and args.refresh_existing and member_id in current_by_id:
                merged_rows.append(normalize_row(current_by_id[member_id], fieldnames))
            else:
                merged_rows.append(normalize_row(row, fieldnames))
        for member_id in new_ids:
            merged_rows.append(normalize_row(current_by_id[member_id], fieldnames))

        if not args.dry_run:
            write_csv_rows(master_csv, fieldnames, merged_rows)
        write_csv_rows(run_dir / "new_members.csv", MEMBER_FIELDS, new_rows)

        detail_target_ids = set(new_ids)
        full_target_ids = set(new_ids)
        if args.fill_missing_existing:
            detail_target_ids.update(
                member_id
                for member_id in current_by_id
                if not is_nonempty_file(faces_dir / f"{member_id}.jpg")
            )
            full_target_ids.update(
                member_id
                for member_id in current_by_id
                if not is_nonempty_file(full_faces_dir / f"{member_id}.jpg")
            )
        detail_rows = [current_by_id[member_id] for member_id in current_by_id if member_id in detail_target_ids]
        full_rows = [current_by_id[member_id] for member_id in current_by_id if member_id in full_target_ids]
        detail_p6s_target_ids = set(detail_target_ids)
        full_p6s_target_ids = set(full_target_ids)
        if args.refresh_existing:
            detail_p6s_target_ids.update(current_by_id)
            full_p6s_target_ids.update(current_by_id)
        if args.fill_missing_existing:
            detail_p6s_target_ids.update(
                member_id
                for member_id in current_by_id
                if not has_p6s_named_file(faces_p6s_named_dir, member_id)
            )
            full_p6s_target_ids.update(
                member_id
                for member_id in current_by_id
                if not has_p6s_named_file(full_faces_p6s_named_dir, member_id)
            )
        detail_p6s_rows = [
            current_by_id[member_id]
            for member_id in current_by_id
            if member_id in detail_p6s_target_ids
        ]
        full_p6s_rows = [
            current_by_id[member_id]
            for member_id in current_by_id
            if member_id in full_p6s_target_ids
        ]

        detail_results: list[dict[str, Any]] = []
        full_results: list[dict[str, Any]] = []
        detail_p6s_results: list[dict[str, Any]] = []
        full_p6s_results: list[dict[str, Any]] = []
        if args.dry_run:
            print("dry-run: skip image downloads and master CSV write")
        else:
            if not args.skip_detail_faces:
                detail_results = download_detail_faces_rows(
                    detail_rows,
                    faces_dir,
                    args.id_column,
                    client,
                    args.app_brand_id,
                    args.app_shop_id,
                    args.detail_url_template,
                    args.face_selector,
                    args.face_wait_seconds,
                    args.detail_f_seed,
                    skip_existing=True,
                )
                write_report_files(
                    run_dir / "detail_faces_report.csv",
                    run_dir / "detail_faces_report.json",
                    detail_results,
                )
                merge_report(faces_dir, detail_results)
            if not args.skip_avatar_full:
                full_results = download_avatar_full_rows(
                    full_rows,
                    full_faces_dir,
                    args.id_column,
                    args.url_column,
                    skip_existing=True,
                )
                write_report_files(
                    run_dir / "avatar_full_report.csv",
                    run_dir / "avatar_full_report.json",
                    full_results,
                )
                merge_report(full_faces_dir, full_results)
            if not args.skip_p6s_named:
                if not args.skip_detail_faces:
                    detail_p6s_results = copy_p6s_named_rows(
                        detail_p6s_rows,
                        faces_dir,
                        faces_p6s_named_dir,
                        args.id_column,
                        [args.p6s_name_column, *args.p6s_fallback_name_column],
                        image_column=None,
                        skip_existing=not args.refresh_existing,
                    )
                    write_p6s_report_files(
                        run_dir / "p6s_detail_faces_report.csv",
                        run_dir / "p6s_detail_faces_report.json",
                        detail_p6s_results,
                    )
                if not args.skip_avatar_full:
                    full_p6s_results = copy_p6s_named_rows(
                        full_p6s_rows,
                        full_faces_dir,
                        full_faces_p6s_named_dir,
                        args.id_column,
                        [args.p6s_name_column, *args.p6s_fallback_name_column],
                        image_column=None,
                        skip_existing=not args.refresh_existing,
                    )
                    write_p6s_report_files(
                        run_dir / "p6s_avatar_full_report.csv",
                        run_dir / "p6s_avatar_full_report.json",
                        full_p6s_results,
                    )

        summary = {
            "list_total": list_meta.get("total"),
            "list_pages": list_meta.get("pages"),
            "current_rows": len(current_rows),
            "master_rows_before": len(master_rows),
            "master_rows_after": len(merged_rows),
            "new_members": len(new_rows),
            "detail_face_targets": len(detail_rows),
            "avatar_full_targets": len(full_rows),
            "detail_face_ok_or_existing": sum(
                1 for result in detail_results if result["status"] in {"ok", "skipped_existing"}
            ),
            "detail_face_failed": sum(1 for result in detail_results if result["status"] == "failed"),
            "avatar_full_ok_or_existing": sum(
                1 for result in full_results if result["status"] in {"ok", "skipped_existing"}
            ),
            "avatar_full_failed": sum(1 for result in full_results if result["status"] == "failed"),
            "p6s_detail_face_targets": len(detail_p6s_rows),
            "p6s_avatar_full_targets": len(full_p6s_rows),
            "p6s_detail_face_ok_or_existing": sum(
                1 for result in detail_p6s_results if result["status"] in {"ok", "skipped_existing"}
            ),
            "p6s_detail_face_failed": sum(1 for result in detail_p6s_results if result["status"] == "failed"),
            "p6s_avatar_full_ok_or_existing": sum(
                1 for result in full_p6s_results if result["status"] in {"ok", "skipped_existing"}
            ),
            "p6s_avatar_full_failed": sum(1 for result in full_p6s_results if result["status"] == "failed"),
            "master_csv": str(master_csv),
            "faces_dir": str(faces_dir),
            "full_faces_dir": str(full_faces_dir),
            "faces_p6s_named_dir": str(faces_p6s_named_dir),
            "full_faces_p6s_named_dir": str(full_faces_p6s_named_dir),
            "run_dir": str(run_dir),
            "dry_run": args.dry_run,
        }
        with (run_dir / "sync_summary.json").open("w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        client.close()


def update_master_csv_with_member(
    master_csv: Path,
    member_row: dict[str, str],
    id_column: str,
    run_dir: Path,
    dry_run: bool,
) -> dict[str, Any]:
    if master_csv.exists():
        master_fieldnames, master_rows = read_csv_rows(master_csv)
        validate_columns(master_fieldnames, [id_column], master_csv)
    else:
        master_fieldnames, master_rows = MEMBER_FIELDS, []

    fieldnames = union_fieldnames(master_fieldnames, MEMBER_FIELDS)
    if id_column not in fieldnames:
        fieldnames.append(id_column)

    member_id = member_row.get(id_column, "").strip()
    merged_rows: list[dict[str, str]] = []
    action = "inserted"
    for row in master_rows:
        if row.get(id_column, "").strip() == member_id:
            merged_rows.append(normalize_row(member_row, fieldnames))
            action = "updated"
        else:
            merged_rows.append(normalize_row(row, fieldnames))
    if action == "inserted":
        merged_rows.append(normalize_row(member_row, fieldnames))

    if not dry_run:
        run_dir.mkdir(parents=True, exist_ok=True)
        if master_csv.exists():
            shutil.copy2(master_csv, run_dir / "master_before.csv")
        write_csv_rows(master_csv, fieldnames, merged_rows)

    return {
        "action": action,
        "master_rows_before": len(master_rows),
        "master_rows_after": len(merged_rows),
        "master_csv": str(master_csv),
    }


def command_refresh_member(args: argparse.Namespace) -> None:
    member_id = args.member_id.strip()
    if not member_id:
        raise StydError("--member-id cannot be empty")

    master_csv = resolve_path(args.master_csv)
    faces_dir = resolve_path(args.faces_dir)
    full_faces_dir = resolve_path(args.full_faces_dir)
    faces_p6s_named_dir = (
        resolve_path(args.faces_p6s_named_dir)
        if args.faces_p6s_named_dir
        else default_p6s_named_dir(faces_dir)
    )
    full_faces_p6s_named_dir = (
        resolve_path(args.full_faces_p6s_named_dir)
        if args.full_faces_p6s_named_dir
        else default_p6s_named_dir(full_faces_dir)
    )
    safe_member_id = "".join(ch for ch in member_id if ch.isalnum() or ch in {"-", "_"}) or "member"
    run_dir = (
        resolve_path(args.run_dir)
        if args.run_dir
        else PROJECT_ROOT
        / "styd_member_sync_runs"
        / f"refresh_{safe_member_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    run_dir.mkdir(parents=True, exist_ok=True)

    ws_url = load_page_websocket_url(args.cdp_url, args.page_url_contains)
    client = CdpClient(ws_url)
    try:
        member_row, list_meta = find_member_in_list(
            client,
            args.list_url,
            member_id,
            wait_seconds=args.list_wait_seconds,
            f_seed=args.list_f_seed,
            max_pages=args.max_pages,
        )
        if args.id_column != "id":
            member_row[args.id_column] = member_id
        write_csv_rows(run_dir / "member_row.csv", MEMBER_FIELDS, [member_row])

        csv_result = update_master_csv_with_member(
            master_csv,
            member_row,
            args.id_column,
            run_dir,
            dry_run=args.dry_run,
        )

        detail_results: list[dict[str, Any]] = []
        full_results: list[dict[str, Any]] = []
        detail_p6s_results: list[dict[str, Any]] = []
        full_p6s_results: list[dict[str, Any]] = []
        if args.dry_run:
            print("dry-run: skip image downloads and master CSV write")
        else:
            if not args.skip_avatar_full:
                full_results = download_avatar_full_rows(
                    [member_row],
                    full_faces_dir,
                    args.id_column,
                    args.url_column,
                    skip_existing=not args.force,
                )
                write_report_files(
                    run_dir / "avatar_full_report.csv",
                    run_dir / "avatar_full_report.json",
                    full_results,
                )
                merge_report(full_faces_dir, full_results)
            if not args.skip_detail_faces:
                detail_results = download_detail_faces_rows(
                    [member_row],
                    faces_dir,
                    args.id_column,
                    client,
                    args.app_brand_id,
                    args.app_shop_id,
                    args.detail_url_template,
                    args.face_selector,
                    args.face_wait_seconds,
                    args.detail_f_seed,
                    skip_existing=not args.force,
                )
                write_report_files(
                    run_dir / "detail_faces_report.csv",
                    run_dir / "detail_faces_report.json",
                    detail_results,
                )
                merge_report(faces_dir, detail_results)
            if not args.skip_p6s_named:
                if not args.skip_avatar_full:
                    full_p6s_results = copy_p6s_named_rows(
                        [member_row],
                        full_faces_dir,
                        full_faces_p6s_named_dir,
                        args.id_column,
                        [args.p6s_name_column, *args.p6s_fallback_name_column],
                        image_column=None,
                        skip_existing=not args.force,
                    )
                    write_p6s_report_files(
                        run_dir / "p6s_avatar_full_report.csv",
                        run_dir / "p6s_avatar_full_report.json",
                        full_p6s_results,
                    )
                if not args.skip_detail_faces:
                    detail_p6s_results = copy_p6s_named_rows(
                        [member_row],
                        faces_dir,
                        faces_p6s_named_dir,
                        args.id_column,
                        [args.p6s_name_column, *args.p6s_fallback_name_column],
                        image_column=None,
                        skip_existing=not args.force,
                    )
                    write_p6s_report_files(
                        run_dir / "p6s_detail_faces_report.csv",
                        run_dir / "p6s_detail_faces_report.json",
                        detail_p6s_results,
                    )

        summary = {
            "member_id": member_id,
            "csv_action": csv_result["action"],
            "master_rows_before": csv_result["master_rows_before"],
            "master_rows_after": csv_result["master_rows_after"],
            "list_pages_scanned": list_meta.get("pages_scanned"),
            "list_total_pages": list_meta.get("total_pages"),
            "avatar_full_url_present": bool(member_row.get(args.url_column, "")),
            "detail_face_status": detail_results[0]["status"] if detail_results else "skipped",
            "avatar_full_status": full_results[0]["status"] if full_results else "skipped",
            "p6s_detail_face_status": detail_p6s_results[0]["status"] if detail_p6s_results else "skipped",
            "p6s_avatar_full_status": full_p6s_results[0]["status"] if full_p6s_results else "skipped",
            "force": args.force,
            "dry_run": args.dry_run,
            "master_csv": str(master_csv),
            "faces_dir": str(faces_dir),
            "full_faces_dir": str(full_faces_dir),
            "faces_p6s_named_dir": str(faces_p6s_named_dir),
            "full_faces_p6s_named_dir": str(full_faces_p6s_named_dir),
            "run_dir": str(run_dir),
        }
        with (run_dir / "refresh_summary.json").open("w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        client.close()


def command_build_p6s_named(args: argparse.Namespace) -> None:
    source_csv = resolve_path(args.source_csv)
    source_dir = resolve_path(args.source_dir)
    output_dir = resolve_path(args.output_dir)
    fieldnames, rows = read_csv_rows(source_csv)
    validate_columns(fieldnames, [args.id_column, args.name_column], source_csv)
    if args.image_column:
        validate_columns(fieldnames, [args.image_column], source_csv)

    target_rows = rows
    if args.id:
        target_ids = set(args.id)
        target_rows = [row for row in rows if row.get(args.id_column, "").strip() in target_ids]

    results = copy_p6s_named_rows(
        target_rows,
        source_dir,
        output_dir,
        args.id_column,
        [args.name_column, *args.fallback_name_column],
        image_column=args.image_column,
        skip_existing=args.skip_existing,
        limit=args.limit,
    )
    write_p6s_report_files(
        output_dir / "_p6s_named_report.csv",
        output_dir / "_p6s_named_report.json",
        results,
    )
    print(
        json.dumps(
            {
                "source_csv": str(source_csv),
                "source_dir": str(source_dir),
                "output_dir": str(output_dir),
                "rows": len(results),
                "ok_or_existing": sum(
                    1 for result in results if result["status"] in {"ok", "skipped_existing"}
                ),
                "failed": sum(1 for result in results if result["status"] == "failed"),
            },
            ensure_ascii=False,
        )
    )


def describe_csv(path: Path) -> dict[str, Any]:
    fieldnames, rows = read_csv_rows(path)
    id_column = "id" if "id" in fieldnames else "member_id" if "member_id" in fieldnames else ""
    ids = [row[id_column] for row in rows if id_column and row.get(id_column)]
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "rows": len(rows),
        "unique_ids": len(set(ids)),
        "empty_ids": len(rows) - len(ids) if id_column else None,
        "avatar_full_nonempty": sum(1 for row in rows if row.get("avatar_full_url")),
        "avatar_thumb_nonempty": sum(1 for row in rows if row.get("avatar_thumb_url")),
        "headers": fieldnames,
    }


def describe_dir(path: Path) -> dict[str, Any]:
    images = [item for item in path.iterdir() if is_image_file(item)]
    report_path = path / "_download_report.csv"
    report: dict[str, Any] | None = None
    if report_path.exists():
        _, rows = read_csv_rows(report_path)
        statuses: dict[str, int] = {}
        for row in rows:
            status = row.get("status", "")
            statuses[status] = statuses.get(status, 0) + 1
        report = {
            "rows": len(rows),
            "unique_ids": len({row.get("member_id") for row in rows if row.get("member_id")}),
            "statuses": statuses,
        }
    sizes = [item.stat().st_size for item in images]
    return {
        "path": str(path),
        "jpg_files": len([item for item in images if item.suffix.lower() == ".jpg"]),
        "image_files": len(images),
        "unique_ids": len({p6s_member_id_from_filename(item) or item.stem for item in images}),
        "total_bytes": sum(sizes),
        "min_bytes": min(sizes, default=0),
        "max_bytes": max(sizes, default=0),
        "report": report,
        "extra_reports": [item.name for item in sorted(path.glob("*report*"))],
    }


def command_summary(args: argparse.Namespace) -> None:
    csv_paths = [resolve_path(value) for value in args.csv]
    if not csv_paths:
        csv_paths = sorted(PROJECT_ROOT.glob("styd_members_*.csv"))
    dir_paths = [resolve_path(value) for value in args.dir]
    if not dir_paths:
        dir_paths = [
            PROJECT_ROOT / "styd_member_faces",
            PROJECT_ROOT / "styd_member_faces_p6s_named",
            PROJECT_ROOT / "styd_member_faces_new_20260630_178",
            PROJECT_ROOT / "styd_member_faces_full",
            PROJECT_ROOT / "styd_member_faces_full_p6s_named",
            PROJECT_ROOT / "teacher_p6s_named",
            PROJECT_ROOT / "staff_p6s_named",
        ]
    payload = {
        "csv": [describe_csv(path) for path in csv_paths if path.exists()],
        "dirs": [describe_dir(path) for path in dir_paths if path.exists()],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Standard STYD member CSV and face-image asset utilities.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    detail = subparsers.add_parser(
        "download-detail-faces",
        help="Use Chrome DevTools to open member detail pages and download biz-face-upload__face images.",
    )
    detail.add_argument("--member-csv", required=True, help="Member CSV containing an id column.")
    detail.add_argument("--output-dir", default="styd_member_faces", help="Directory for <id>.jpg files.")
    detail.add_argument("--id-column", default="id")
    detail.add_argument("--app-brand-id", default=DEFAULT_APP_BRAND_ID)
    detail.add_argument("--app-shop-id", default=DEFAULT_APP_SHOP_ID)
    detail.add_argument("--detail-url-template", help="Optional Python format template with {id}, {app_brand_id}, {app_shop_id}, {f}.")
    detail.add_argument("--cdp-url", default=DEFAULT_CDP_URL)
    detail.add_argument("--page-url-contains", default="pro.styd.cn")
    detail.add_argument("--face-selector", default=DEFAULT_FACE_SELECTOR)
    detail.add_argument("--wait-seconds", type=float, default=22.0)
    detail.add_argument("--f-seed", type=int, default=12000)
    detail.add_argument("--limit", type=int)
    detail.add_argument("--skip-existing", action=argparse.BooleanOptionalAction, default=True)
    detail.add_argument("--p6s-named-dir", help="Optional P6S named-copy output directory.")
    detail.add_argument("--p6s-name-column", default="nickname")
    detail.add_argument("--p6s-fallback-name-column", action="append", default=["member_name"])
    detail.add_argument("--skip-p6s-named", action="store_true")
    detail.set_defaults(func=command_download_detail_faces)

    full = subparsers.add_parser(
        "download-avatar-full",
        help="Download images from avatar_full_url in a member CSV.",
    )
    full.add_argument("--member-csv", required=True)
    full.add_argument("--output-dir", default="styd_member_faces_full")
    full.add_argument("--id-column", default="id")
    full.add_argument("--url-column", default="avatar_full_url")
    full.add_argument("--limit", type=int)
    full.add_argument("--skip-existing", action=argparse.BooleanOptionalAction, default=True)
    full.add_argument("--p6s-named-dir", help="Optional P6S named-copy output directory.")
    full.add_argument("--p6s-name-column", default="nickname")
    full.add_argument("--p6s-fallback-name-column", action="append", default=["member_name"])
    full.add_argument("--skip-p6s-named", action="store_true")
    full.set_defaults(func=command_download_avatar_full)

    filter_cmd = subparsers.add_parser(
        "filter-by-faces",
        help="Filter member CSV rows whose id has a matching <id>.jpg in a face directory.",
    )
    filter_cmd.add_argument("--member-csv", required=True)
    filter_cmd.add_argument("--faces-dir", required=True)
    filter_cmd.add_argument("--output-csv", required=True)
    filter_cmd.add_argument("--id-column", default="id")
    filter_cmd.add_argument("--allow-missing", action="store_true")
    filter_cmd.set_defaults(func=command_filter_by_faces)

    split = subparsers.add_parser(
        "split-by-mtime",
        help="Copy or move images newer than a cutoff into a separate directory.",
    )
    split.add_argument("--source-dir", required=True)
    split.add_argument("--dest-dir", required=True)
    split.add_argument("--cutoff", required=True, help="ISO timestamp, for example '2026-06-30 00:00:00'.")
    split.add_argument("--expected-count", type=int)
    split.add_argument("--move", action="store_true", help="Move files instead of copying them.")
    split.add_argument("--allow-nonempty-dest", action="store_true")
    split.set_defaults(func=command_split_by_mtime)

    sync = subparsers.add_parser(
        "incremental-sync",
        help="Scrape the current list, append new member ids to a master CSV, and fill face image directories.",
    )
    sync.add_argument("--list-url", required=True, help="Filtered STYD member-list URL to scrape.")
    sync.add_argument("--master-csv", required=True, help="Canonical member CSV to append new ids into.")
    sync.add_argument("--faces-dir", default="styd_member_faces", help="Directory for detail-page face images.")
    sync.add_argument("--full-faces-dir", default="styd_member_faces_full", help="Directory for avatar_full_url images.")
    sync.add_argument("--faces-p6s-named-dir", help="Directory for P6S-named detail-page face copies.")
    sync.add_argument("--full-faces-p6s-named-dir", help="Directory for P6S-named avatar_full copies.")
    sync.add_argument("--run-dir", help="Directory for this run's current_members/new_members/reports.")
    sync.add_argument("--id-column", default="id")
    sync.add_argument("--url-column", default="avatar_full_url")
    sync.add_argument("--p6s-name-column", default="nickname")
    sync.add_argument("--p6s-fallback-name-column", action="append", default=["member_name"])
    sync.add_argument("--app-brand-id", default=DEFAULT_APP_BRAND_ID)
    sync.add_argument("--app-shop-id", default=DEFAULT_APP_SHOP_ID)
    sync.add_argument("--detail-url-template", help="Optional Python format template with {id}, {app_brand_id}, {app_shop_id}, {f}.")
    sync.add_argument("--cdp-url", default=DEFAULT_CDP_URL)
    sync.add_argument("--page-url-contains", default="pro.styd.cn")
    sync.add_argument("--face-selector", default=DEFAULT_FACE_SELECTOR)
    sync.add_argument("--list-wait-seconds", type=float, default=25.0)
    sync.add_argument("--face-wait-seconds", type=float, default=22.0)
    sync.add_argument("--list-f-seed", type=int, default=20000)
    sync.add_argument("--detail-f-seed", type=int, default=30000)
    sync.add_argument("--max-pages", type=int, help="Limit scraped pages for a smoke test.")
    sync.add_argument(
        "--fill-missing-existing",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Also download images for existing ids when the target image file is missing.",
    )
    sync.add_argument(
        "--refresh-existing",
        action="store_true",
        help="Refresh existing CSV rows from the newly scraped list instead of only appending new ids.",
    )
    sync.add_argument("--skip-detail-faces", action="store_true", help="Do not download detail-page face images.")
    sync.add_argument("--skip-avatar-full", action="store_true", help="Do not download avatar_full_url images.")
    sync.add_argument("--skip-p6s-named", action="store_true", help="Do not generate P6S-named image copies.")
    sync.add_argument("--dry-run", action="store_true", help="Scrape and diff only; do not write master CSV or download images.")
    sync.set_defaults(func=command_incremental_sync)

    refresh = subparsers.add_parser(
        "refresh-member",
        help="Refresh one member by id: update its CSV row, avatar_full image, and detail-page face image.",
    )
    refresh.add_argument("--member-id", required=True, help="STYD member id to refresh.")
    refresh.add_argument("--list-url", required=True, help="Filtered STYD member-list URL containing the member.")
    refresh.add_argument("--master-csv", required=True, help="Canonical member CSV to update or append into.")
    refresh.add_argument("--faces-dir", default="styd_member_faces", help="Directory for detail-page face images.")
    refresh.add_argument("--full-faces-dir", default="styd_member_faces_full", help="Directory for avatar_full_url images.")
    refresh.add_argument("--faces-p6s-named-dir", help="Directory for P6S-named detail-page face copies.")
    refresh.add_argument("--full-faces-p6s-named-dir", help="Directory for P6S-named avatar_full copies.")
    refresh.add_argument("--run-dir", help="Directory for this refresh run's row snapshot and reports.")
    refresh.add_argument("--id-column", default="id")
    refresh.add_argument("--url-column", default="avatar_full_url")
    refresh.add_argument("--p6s-name-column", default="nickname")
    refresh.add_argument("--p6s-fallback-name-column", action="append", default=["member_name"])
    refresh.add_argument("--app-brand-id", default=DEFAULT_APP_BRAND_ID)
    refresh.add_argument("--app-shop-id", default=DEFAULT_APP_SHOP_ID)
    refresh.add_argument("--detail-url-template", help="Optional Python format template with {id}, {app_brand_id}, {app_shop_id}, {f}.")
    refresh.add_argument("--cdp-url", default=DEFAULT_CDP_URL)
    refresh.add_argument("--page-url-contains", default="pro.styd.cn")
    refresh.add_argument("--face-selector", default=DEFAULT_FACE_SELECTOR)
    refresh.add_argument("--list-wait-seconds", type=float, default=25.0)
    refresh.add_argument("--face-wait-seconds", type=float, default=22.0)
    refresh.add_argument("--list-f-seed", type=int, default=40000)
    refresh.add_argument("--detail-f-seed", type=int, default=50000)
    refresh.add_argument("--max-pages", type=int, help="Limit scanned list pages for a smoke test.")
    refresh.add_argument(
        "--force",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Overwrite existing images. Use --no-force to only fill missing files.",
    )
    refresh.add_argument("--skip-detail-faces", action="store_true", help="Do not download the detail-page face image.")
    refresh.add_argument("--skip-avatar-full", action="store_true", help="Do not download the avatar_full_url image.")
    refresh.add_argument("--skip-p6s-named", action="store_true", help="Do not generate P6S-named image copies.")
    refresh.add_argument("--dry-run", action="store_true", help="Find and diff only; do not write master CSV or download images.")
    refresh.set_defaults(func=command_refresh_member)

    p6s = subparsers.add_parser(
        "build-p6s-named",
        help="Build P6S-named image copies from a CSV and a source image directory.",
    )
    p6s.add_argument("--source-csv", required=True)
    p6s.add_argument("--source-dir", required=True)
    p6s.add_argument("--output-dir", required=True)
    p6s.add_argument("--id-column", default="id")
    p6s.add_argument("--name-column", default="nickname")
    p6s.add_argument("--fallback-name-column", action="append", default=[])
    p6s.add_argument("--image-column", help="Optional CSV column containing source image filenames.")
    p6s.add_argument("--id", action="append", help="Only build selected ID; may be repeated.")
    p6s.add_argument("--limit", type=int)
    p6s.add_argument("--skip-existing", action=argparse.BooleanOptionalAction, default=False)
    p6s.set_defaults(func=command_build_p6s_named)

    summary = subparsers.add_parser("summary", help="Summarize STYD CSV files and image directories.")
    summary.add_argument("--csv", action="append", default=[], help="CSV path; may be repeated.")
    summary.add_argument("--dir", action="append", default=[], help="Image directory; may be repeated.")
    summary.set_defaults(func=command_summary)

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        args.func(args)
        return 0
    except StydError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
