"""Import member, coach, and staff CSV rows into attendance people tables."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.db.config import load_env_file


@dataclass(frozen=True)
class RoleSpec:
    code: str
    label: str
    default_csv: str
    id_column: str
    name_column: str
    group_env: str
    default_expected_count: int


ROLE_SPECS = {
    "member": RoleSpec(
        code="member",
        label="会员",
        default_csv="styd_members_20260703_existing_faces_244.csv",
        id_column="id",
        name_column="member_name",
        group_env="P6S_FACE_GROUP_MEMBERS_ID",
        default_expected_count=244,
    ),
    "coach": RoleSpec(
        code="coach",
        label="教练",
        default_csv="teacher.csv",
        id_column="ID",
        name_column="姓名",
        group_env="P6S_FACE_GROUP_COACHES_ID",
        default_expected_count=15,
    ),
    "staff": RoleSpec(
        code="staff",
        label="员工",
        default_csv="staff.csv",
        id_column="ID",
        name_column="姓名",
        group_env="P6S_FACE_GROUP_STAFF_ID",
        default_expected_count=4,
    ),
}

PLACEHOLDER_GROUP_IDS = {"members", "coaches", "staff"}


def main() -> int:
    args = parse_args()
    if args.env_file:
        load_env_file(args.env_file)

    roles = args.roles or list(ROLE_SPECS)
    expected_counts = {
        "member": args.expected_members,
        "coach": args.expected_coaches,
        "staff": args.expected_staff,
    }

    people_by_role: dict[str, list[dict[str, Any]]] = {}
    report: dict[str, Any] = {
        "apply": args.apply,
        "env_file": str(args.env_file) if args.env_file else None,
        "roles": {},
        "warnings": [],
        "errors": [],
    }

    seen_global: dict[str, str] = {}
    for role in roles:
        spec = ROLE_SPECS[role]
        csv_path = csv_path_for(args, spec)
        group_id = os.environ.get(spec.group_env, "").strip()
        role_report, people = read_people_csv(
            spec=spec,
            csv_path=csv_path,
            group_id=group_id,
            expected_count=expected_counts[role],
            apply=args.apply,
        )
        report["roles"][role] = role_report
        people_by_role[role] = people
        report["warnings"].extend(role_report["warnings"])
        report["errors"].extend(role_report["errors"])

        for person in people:
            previous_role = seen_global.get(person["person_ref_id"])
            if previous_role and previous_role != role:
                report["warnings"].append(
                    {
                        "role": role,
                        "message": "same person id appears in multiple roles",
                        "person_ref_id": person["person_ref_id"],
                        "previous_role": previous_role,
                    }
                )
            seen_global.setdefault(person["person_ref_id"], role)

    if report["errors"]:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    if args.apply:
        applied = apply_people(people_by_role)
        report["applied"] = applied
    else:
        report["dry_run"] = True

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.local")
    parser.add_argument("--role", dest="roles", action="append", choices=sorted(ROLE_SPECS))
    parser.add_argument("--members-csv", type=Path, default=PROJECT_ROOT / ROLE_SPECS["member"].default_csv)
    parser.add_argument("--coaches-csv", type=Path, default=PROJECT_ROOT / ROLE_SPECS["coach"].default_csv)
    parser.add_argument("--staff-csv", type=Path, default=PROJECT_ROOT / ROLE_SPECS["staff"].default_csv)
    parser.add_argument("--expected-members", type=int, default=ROLE_SPECS["member"].default_expected_count)
    parser.add_argument("--expected-coaches", type=int, default=ROLE_SPECS["coach"].default_expected_count)
    parser.add_argument("--expected-staff", type=int, default=ROLE_SPECS["staff"].default_expected_count)
    parser.add_argument("--apply", action="store_true", help="Write rows to PostgreSQL. Omit for dry-run.")
    return parser.parse_args()


def csv_path_for(args: argparse.Namespace, spec: RoleSpec) -> Path:
    if spec.code == "member":
        return args.members_csv
    if spec.code == "coach":
        return args.coaches_csv
    if spec.code == "staff":
        return args.staff_csv
    raise ValueError(f"unsupported role: {spec.code}")


def read_people_csv(
    *,
    spec: RoleSpec,
    csv_path: Path,
    group_id: str,
    expected_count: int,
    apply: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    people: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    if not csv_path.exists():
        errors.append({"role": spec.code, "message": "csv file does not exist", "path": str(csv_path)})
        return _role_report(spec, csv_path, group_id, expected_count, people, warnings, errors), people

    if not group_id:
        errors.append({"role": spec.code, "message": f"missing required group env {spec.group_env}"})
    elif _looks_placeholder_group(group_id):
        item = {"role": spec.code, "message": f"group env {spec.group_env} looks like a placeholder"}
        if apply:
            errors.append(item)
        else:
            warnings.append(item)

    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            errors.append({"role": spec.code, "message": "csv has no header", "path": str(csv_path)})
            return _role_report(spec, csv_path, group_id, expected_count, people, warnings, errors), people
        for required in (spec.id_column, spec.name_column):
            if required not in reader.fieldnames:
                errors.append(
                    {
                        "role": spec.code,
                        "message": "csv missing required column",
                        "column": required,
                        "path": str(csv_path),
                    }
                )
        if errors:
            return _role_report(spec, csv_path, group_id, expected_count, people, warnings, errors), people

        for row_number, row in enumerate(reader, start=2):
            person_id = (row.get(spec.id_column) or "").strip()
            name = (row.get(spec.name_column) or "").strip()
            if not person_id:
                errors.append({"role": spec.code, "row": row_number, "message": "empty person id"})
                continue
            if not name:
                errors.append({"role": spec.code, "row": row_number, "message": "empty name", "person_id": person_id})
                continue
            if person_id in seen_ids:
                errors.append({"role": spec.code, "row": row_number, "message": "duplicate id", "person_id": person_id})
                continue
            seen_ids.add(person_id)
            people.append(
                {
                    "person_ref_id": person_id,
                    "name": name,
                    "face_group_id": group_id,
                    "camera_person_id": None,
                }
            )

    if expected_count >= 0 and len(people) != expected_count:
        errors.append(
            {
                "role": spec.code,
                "message": "csv valid row count does not match expected count",
                "expected": expected_count,
                "actual": len(people),
            }
        )
    return _role_report(spec, csv_path, group_id, expected_count, people, warnings, errors), people


def apply_people(people_by_role: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    from app.db import attendance_repo
    from app.db.session import transaction

    applied: dict[str, int] = {}
    with transaction() as conn:
        for role, people in people_by_role.items():
            applied[role] = attendance_repo.upsert_people(conn, role, people)
    return applied


def _role_report(
    spec: RoleSpec,
    csv_path: Path,
    group_id: str,
    expected_count: int,
    people: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "label": spec.label,
        "csv_path": str(csv_path),
        "id_column": spec.id_column,
        "name_column": spec.name_column,
        "group_env": spec.group_env,
        "group_id_configured": bool(group_id),
        "expected_count": expected_count,
        "valid_count": len(people),
        "warnings": warnings,
        "errors": errors,
    }


def _looks_placeholder_group(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized.startswith("replace-with") or normalized in PLACEHOLDER_GROUP_IDS


if __name__ == "__main__":
    raise SystemExit(main())
