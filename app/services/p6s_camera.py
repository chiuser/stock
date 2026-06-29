"""P6S camera HTTP helpers.

The camera documentation uses plain HTTP CGI endpoints with Basic Auth for
device configuration and face-library writes.  This module keeps those details
away from FastAPI route code so the admin page can call a small, stable API.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from string import Formatter
from typing import Any
from urllib.parse import urlparse
from xml.sax.saxutils import escape

import requests
from requests.auth import HTTPBasicAuth


DEFAULT_PERSON_XML_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<FaceGroupPersonInfo>
  <FaceGroupID>{face_group_id}</FaceGroupID>
  <FaceUUID>{face_uuid}</FaceUUID>
  <Name>{name}</Name>
  <Sex>unknown</Sex>
  <UniqueID>{unique_id}</UniqueID>
  <FaceImage>{image_base64}</FaceImage>
  <Ownner>{safety_code}</Ownner>
  <SystemTime>{system_time}</SystemTime>
</FaceGroupPersonInfo>"""


@dataclass(frozen=True)
class P6SConfig:
    base_url: str
    username: str
    password: str
    owner: str
    face_group_id: str
    face_group_name: str
    face_group_threshold: int | None
    person_xml_template: str

    @classmethod
    def from_env(cls) -> "P6SConfig":
        raw_base = os.environ.get("P6S_CAMERA_BASE_URL", "").strip()
        raw_host = os.environ.get("P6S_CAMERA_HOST", "").strip()
        base_url = raw_base or raw_host
        if base_url and "://" not in base_url:
            base_url = f"http://{base_url}"
        base_url = base_url.rstrip("/")

        threshold_raw = os.environ.get("P6S_FACE_GROUP_THRESHOLD", "").strip()
        threshold = int(threshold_raw) if threshold_raw.isdigit() else None

        return cls(
            base_url=base_url,
            username=os.environ.get("P6S_CAMERA_USERNAME", "").strip(),
            password=os.environ.get("P6S_CAMERA_PASSWORD", "").strip(),
            owner=os.environ.get("P6S_FACE_OWNER", "").strip(),
            face_group_id=os.environ.get("P6S_FACE_GROUP_ID", "members").strip(),
            face_group_name=os.environ.get("P6S_FACE_GROUP_NAME", "会员人脸库").strip(),
            face_group_threshold=threshold,
            person_xml_template=os.environ.get(
                "P6S_PERSON_XML_TEMPLATE",
                DEFAULT_PERSON_XML_TEMPLATE,
            ),
        )

    def configured(self) -> bool:
        return bool(self.base_url and self.username and self.password)

    def safe_summary(self) -> dict[str, Any]:
        parsed = urlparse(self.base_url) if self.base_url else None
        return {
            "configured": self.configured(),
            "base_url": self.base_url,
            "host": parsed.netloc if parsed else "",
            "username": self.username,
            "has_password": bool(self.password),
            "has_owner": bool(self.owner),
            "face_group_id": self.face_group_id,
            "face_group_name": self.face_group_name,
            "face_group_threshold": self.face_group_threshold,
            "has_custom_person_xml_template": (
                self.person_xml_template != DEFAULT_PERSON_XML_TEMPLATE
            ),
        }


def generate_owner() -> str:
    """Generate the persistent face-library owner marker.

    The docs emphasize that this owner value must be saved and reused; changing
    it later breaks safety-code generation for face-library writes.
    """

    return base64.urlsafe_b64encode(secrets.token_bytes(16)).decode().rstrip("=")


def system_time() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def generate_safety_code(owner: str, system_time_value: str) -> str:
    """Generate the P6S face-library safety code from owner + system time."""

    digest = hashlib.md5(f"{owner}{system_time_value}".encode()).hexdigest()
    return digest[:8][::-1]


def _xml(value: Any) -> str:
    return escape("" if value is None else str(value))


class P6SCameraClient:
    def __init__(self, config: P6SConfig | None = None):
        self.config = config or P6SConfig.from_env()

    def _request(
        self,
        method: str,
        path: str,
        body: str | None = None,
        content_type: str = "application/xml",
        timeout: int = 15,
    ) -> dict[str, Any]:
        if not self.config.configured():
            return {
                "ok": False,
                "status_code": None,
                "url": path,
                "text": "P6S camera is not configured",
            }

        url = f"{self.config.base_url}{path}"
        headers = {"Content-Type": content_type}
        try:
            response = requests.request(
                method=method.upper(),
                url=url,
                data=body.encode("utf-8") if body is not None else None,
                headers=headers,
                auth=HTTPBasicAuth(self.config.username, self.config.password),
                timeout=timeout,
            )
            return {
                "ok": 200 <= response.status_code < 300,
                "status_code": response.status_code,
                "url": url,
                "text": response.text,
            }
        except requests.RequestException as exc:
            return {
                "ok": False,
                "status_code": None,
                "url": url,
                "text": str(exc),
            }

    def get_owner(self) -> dict[str, Any]:
        return self._request("GET", "/System/FrontDeviceOwnnerInfo")

    def set_owner(self, owner: str) -> dict[str, Any]:
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            "<FrontDeviceOwnnerInfo>"
            f"<Ownner>{_xml(owner)}</Ownner>"
            "</FrontDeviceOwnnerInfo>"
        )
        return self._request("PUT", "/System/FrontDeviceOwnnerInfo", body)

    def query_groups(self) -> dict[str, Any]:
        return self._request("PUT", "/FaceGroups/QueryAll", "")

    def create_group(
        self,
        group_id: str | None = None,
        group_name: str | None = None,
        owner: str | None = None,
        threshold: int | None = None,
    ) -> dict[str, Any]:
        owner_value = owner or self.config.owner
        if not owner_value:
            return {
                "ok": False,
                "status_code": None,
                "url": "/FaceGroups/Create",
                "text": "P6S_FACE_OWNER is required",
            }

        ts = system_time()
        safety_code = generate_safety_code(owner_value, ts)
        threshold_value = (
            threshold
            if threshold is not None
            else self.config.face_group_threshold
        )
        threshold_xml = (
            f"<GroupThresholdValue>{int(threshold_value)}</GroupThresholdValue>"
            if threshold_value is not None
            else ""
        )
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            "<FaceGroup>"
            f"<GroupName>{_xml(group_name or self.config.face_group_name)}</GroupName>"
            f"<GroupID2>{_xml(group_id or self.config.face_group_id)}</GroupID2>"
            f"{threshold_xml}"
            f"<Ownner>{_xml(safety_code)}</Ownner>"
            f"<SystemTime>{_xml(ts)}</SystemTime>"
            "</FaceGroup>"
        )
        result = self._request("PUT", "/FaceGroups/Create", body)
        result["system_time"] = ts
        return result

    def upload_person_image(
        self,
        image_path: Path,
        unique_id: str,
        name: str | None = None,
        face_group_id: str | None = None,
        owner: str | None = None,
        face_uuid: str = "",
    ) -> dict[str, Any]:
        owner_value = owner or self.config.owner
        if not owner_value:
            return {
                "ok": False,
                "status_code": None,
                "url": "/FaceGroup/UpdatePersonInfoAndFaceImage",
                "text": "P6S_FACE_OWNER is required",
            }
        if not image_path.exists():
            return {
                "ok": False,
                "status_code": None,
                "url": "/FaceGroup/UpdatePersonInfoAndFaceImage",
                "text": f"image not found: {image_path}",
            }

        raw_image = image_path.read_bytes()
        image_base64 = base64.b64encode(raw_image).decode()
        ts = system_time()
        safety_code = generate_safety_code(owner_value, ts)

        values = {
            "face_group_id": _xml(face_group_id or self.config.face_group_id),
            "face_uuid": _xml(face_uuid),
            "name": _xml(name or unique_id),
            "unique_id": _xml(unique_id),
            "image_base64": image_base64,
            "image_data_url": f"data:image/jpeg;base64,{image_base64}",
            "safety_code": _xml(safety_code),
            "system_time": _xml(ts),
            "image_bytes": len(raw_image),
        }
        body = _safe_template_format(self.config.person_xml_template, values)
        result = self._request(
            "PUT",
            "/FaceGroup/UpdatePersonInfoAndFaceImage",
            body,
            timeout=30,
        )
        result.update(
            {
                "member_id": unique_id,
                "image_path": str(image_path),
                "image_bytes": len(raw_image),
                "system_time": ts,
            }
        )
        return result


def _safe_template_format(template: str, values: dict[str, Any]) -> str:
    """Format an XML template while failing clearly on unsupported fields."""

    allowed = {name for _, name, _, _ in Formatter().parse(template) if name}
    missing = sorted(allowed - set(values))
    if missing:
        raise ValueError(f"Unsupported P6S_PERSON_XML_TEMPLATE fields: {missing}")
    return template.format(**values)

