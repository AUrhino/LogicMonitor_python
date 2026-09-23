#!/usr/bin/env python3
"""
LogicMonitor LogAlert Groups / LogAlerts REST API utility.

Created by Ryan Gillan

Actions:
  --show-tree   GET /logpipelines and /logpipelines/processors
  --backup      Backup both endpoints to JSON
  --create      POST one JSON object, or one selected object from a backup
  --restore     Restore an entire backup, remapping pipeline IDs
  --debug       Show safe HTTP diagnostics
  --version     Show utility version

Credentials:
  .env by default
  --creds-file PATH selects an alternate dotenv file

Required credentials in the dotenv file:
  ACCESS_ID
  ACCESS_KEY
  COMPANY

Optional:
  LM_BASE_URL

The restore operation is CREATE ONLY. It does not delete or replace
existing LogAlert Groups or LogAlerts.
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import time
from datetime import datetime, timezone
from html import escape as html_escape
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv
from tabulate import tabulate


__version__ = "1.03"
__author__ = "Ryan Gillan"

DEFAULT_CREDS_FILE = ".env"
LOGPIPELINES_PATH = "/logpipelines"
PROCESSORS_PATH = "/logpipelines/processors"
DEFAULT_PAGE_SIZE = 200
DEFAULT_TIMEOUT = 30
DEFAULT_PARTITION = "default"

ACCESS_ID: Optional[str] = None
ACCESS_KEY: Optional[str] = None
COMPANY: Optional[str] = None
BASE_URL = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def die(message: str, exit_code: int = 2) -> None:
    print(f"Error: {message}", file=sys.stderr)
    raise SystemExit(exit_code)

def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()

def json_default(value: Any) -> str:
    return str(value)

def first_value(
    obj: Dict[str, Any],
    names: Sequence[str],
    default: Any = None,
) -> Any:
    for name in names:
        if name in obj and obj[name] not in (None, ""):
            return obj[name]
    return default

def pretty_value(value: Any, max_len: int = 100) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    else:
        value = str(value)

    value = value.replace("\n", "\\n")

    if len(value) > max_len:
        return value[:max_len - 3] + "..."

    return value


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------
def load_credentials(creds_file: str = DEFAULT_CREDS_FILE) -> None:
    global ACCESS_ID, ACCESS_KEY, COMPANY, BASE_URL

    dotenv_path = Path(creds_file).expanduser()

    if not dotenv_path.is_file():
        die(f"Credentials file does not exist: {dotenv_path}")

    load_dotenv(
        dotenv_path=dotenv_path,
        override=True,
    )

    ACCESS_ID = os.getenv("ACCESS_ID")
    ACCESS_KEY = os.getenv("ACCESS_KEY")
    COMPANY = os.getenv("COMPANY")

    BASE_URL = os.getenv(
        "LM_BASE_URL",
        (
            f"https://{COMPANY}.logicmonitor.com/santaba/rest"
            if COMPANY
            else ""
        ),
    ).rstrip("/")


def require_credentials() -> None:
    missing = [
        name
        for name, value in (
            ("ACCESS_ID", ACCESS_ID),
            ("ACCESS_KEY", ACCESS_KEY),
            ("COMPANY", COMPANY),
        )
        if not value
    ]

    if missing:
        die(
            "Missing required environment variable(s): "
            + ", ".join(missing)
        )

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args(
    argv: Optional[Sequence[str]] = None,
) -> argparse.Namespace:

    examples = r"""
Examples:
  # Show all pipelines and processors as an ASCII tree.
  python3 Get-LMLogAlerts.py --show-tree

  # Use a different credential file.
  python3 Get-LMLogAlerts.py --show-tree --creds-file .sample

  # Back up both LogAlert Groups and LogAlerts.
  python3 Get-LMLogAlerts.py --backup output/sample.json

  # Create one processor from a standalone JSON payload.
  python3 Get-LMLogAlerts.py \
      --create processor.json \
      --create-kind processor

  # Create one processor from a backup.
  python3 Get-LMLogAlerts.py \
      --create output/sample.json \
      --create-kind processor \
      --create-id 78

  # Restore the COMPLETE backup. Pipelines are created first and their
  # new IDs are automatically applied to processors.
  python3 Get-LMLogAlerts.py \
      --creds-file .sample \
      --restore output/sample.json \
      --restore-results output/restore-results.json \
      --debug

  # Create an HTML tree/table. Table columns are horizontally resizable.
  python3 Get-LMLogAlerts.py \
      --show-tree \
      --html output/logalerts.html

Notes:
  - Running with no arguments displays this help.
  - --backup is read-only.
  - --restore performs POST operations only; it does NOT delete anything.
  - A backup restore creates every pipeline first, records old->new pipeline IDs, then creates every processor with the new pipelineId.
  - --create-id is required when using a backup with --create.
  - ACCESS_KEY is never printed.
"""

    parser = argparse.ArgumentParser(
        description=(
            f"LogicMonitor LogAlert Groups / LogAlerts utility "
            f"v{__version__} (Created by {__author__})."
        ),
        epilog=examples,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    actions = parser.add_mutually_exclusive_group()

    actions.add_argument(
        "--show-tree",
        action="store_true",
        help="GET LogAlert Groups and LogAlerts and show an ASCII tree.",
    )

    actions.add_argument(
        "--backup",
        metavar="PATH",
        help="Back up both LogAlert endpoints to PATH.",
    )

    actions.add_argument(
        "--create",
        metavar="PATH",
        help="POST one object, or one object selected from a backup.",
    )

    actions.add_argument(
        "--restore",
        metavar="PATH",
        help="Restore every object in a LogAlert backup.",
    )

    parser.add_argument(
        "--creds-file",
        metavar="PATH",
        default=DEFAULT_CREDS_FILE,
        help=f"dotenv credential file (default: {DEFAULT_CREDS_FILE}).",
    )

    parser.add_argument(
        "--partition",
        metavar="NAME",
        default=DEFAULT_PARTITION,
        help=(
            f"Log partition used when a backup pipeline has no partition "
            f"metadata (default: {DEFAULT_PARTITION})."
        ),
    )

    parser.add_argument(
        "--create-kind",
        choices=("pipeline", "processor"),
        help="Object type for --create.",
    )

    parser.add_argument(
        "--create-id",
        metavar="ID",
        help="Select one object by ID when --create uses a backup.",
    )

    parser.add_argument(
        "--pipeline-id",
        metavar="ID",
        help="Limit --show-tree to one LogAlert Group ID.",
    )

    parser.add_argument(
        "--filter",
        help="Optional LogicMonitor filter expression for GET requests.",
    )

    parser.add_argument(
        "--size",
        type=int,
        default=DEFAULT_PAGE_SIZE,
        help=f"GET page size (default: {DEFAULT_PAGE_SIZE}).",
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"HTTP timeout seconds (default: {DEFAULT_TIMEOUT}).",
    )

    parser.add_argument(
        "--html",
        metavar="PATH",
        help="Write an HTML tree/table with horizontally resizable columns.",
    )

    parser.add_argument(
        "--raw",
        action="store_true",
        help="Print complete GET JSON after normal output.",
    )

    parser.add_argument(
        "--restore-results",
        metavar="PATH",
        help="Write restore mappings/results to PATH.",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print safe HTTP request diagnostics.",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"{__version__} (Created by {__author__})",
    )

    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# LMv1 authentication / HTTP
# ---------------------------------------------------------------------------

def lm_headers(
    method: str,
    path: str,
    body_bytes: bytes = b"",
) -> Dict[str, str]:
    """
    LogicMonitor LMv1 signing.

    Signing string:
      HTTP_VERB + EPOCH + REQUEST_BODY(if any) + RESOURCE_PATH
    """

    if not ACCESS_ID or not ACCESS_KEY:
        die("Credentials have not been loaded.")

    epoch = str(int(time.time() * 1000))
    verb = method.upper()

    signing = verb + epoch

    if body_bytes:
        signing += body_bytes.decode("utf-8")

    signing += path

    digest = hmac.new(
        ACCESS_KEY.encode("utf-8"),
        signing.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    signature = base64.b64encode(
        digest.encode("utf-8")
    ).decode("ascii")

    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Version": "3",
        "Authorization": (
            f"LMv1 {ACCESS_ID}:{signature}:{epoch}"
        ),
    }


def api_request(
    method: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    payload: Optional[Dict[str, Any]] = None,
    timeout: float = DEFAULT_TIMEOUT,
    debug: bool = False,
) -> Any:

    body_bytes = b""

    if payload is not None:
        body_bytes = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

    url = BASE_URL + path

    clean_params = {
        key: value
        for key, value in (params or {}).items()
        if value not in (None, "")
    }

    if clean_params:
        url += "?" + urlencode(
            clean_params,
            doseq=True,
        )

    headers = lm_headers(
        method,
        path,
        body_bytes,
    )

    if debug:
        print(f"[DEBUG] {method.upper()} {url}")

        if body_bytes:
            print(
                f"[DEBUG] Request JSON bytes: "
                f"{len(body_bytes)}"
            )

        print(
            "[DEBUG] Authorization: "
            "LMv1 <redacted>"
        )

    try:
        response = requests.request(
            method.upper(),
            url,
            headers=headers,
            data=body_bytes if body_bytes else None,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        die(
            f"HTTP request failed for "
            f"{method.upper()} {path}: {exc}",
            exit_code=1,
        )

    if debug:
        print(
            f"[DEBUG] HTTP {response.status_code}"
        )
        print(
            "[DEBUG] Response content type: "
            f"{response.headers.get('Content-Type', '')}"
        )

        if response.status_code == 401:
            print("[DEBUG] Authentication: FAILED")
        else:
            print(
                "[DEBUG] Authentication: SUCCESS "
                "(request reached API authorization/validation)"
            )

    if not response.ok:
        preview = (
            response.text
            .strip()
            .replace("\n", " ")
        )

        if len(preview) > 1000:
            preview = preview[:997] + "..."

        die(
            f"{method.upper()} {path} returned HTTP "
            f"{response.status_code}. Response: {preview}",
            exit_code=1,
        )

    if not response.content:
        return {}

    try:
        return response.json()
    except ValueError:
        return response.text


# ---------------------------------------------------------------------------
# GET / pagination
# ---------------------------------------------------------------------------

def unwrap_data(payload: Any) -> Any:
    if isinstance(payload, dict):
        if payload.get("data") is not None:
            return payload["data"]

        if "items" in payload:
            return payload["items"]

    return payload


def extract_items(payload: Any) -> List[Dict[str, Any]]:
    data = unwrap_data(payload)

    if isinstance(data, list):
        return [
            item
            for item in data
            if isinstance(item, dict)
        ]

    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return [
                item
                for item in items
                if isinstance(item, dict)
            ]

    return []


def get_all(
    path: str,
    filter_expression: Optional[str],
    size: int,
    timeout: float,
    debug: bool,
) -> Tuple[List[Dict[str, Any]], List[Any]]:

    if size < 1:
        die("--size must be greater than zero.")

    offset = 0
    all_items: List[Dict[str, Any]] = []
    raw_pages: List[Any] = []

    while True:
        params: Dict[str, Any] = {
            "size": size,
            "offset": offset,
        }

        if filter_expression:
            params["filter"] = filter_expression

        payload = api_request(
            "GET",
            path,
            params=params,
            timeout=timeout,
            debug=debug,
        )

        raw_pages.append(payload)

        page = extract_items(payload)
        all_items.extend(page)

        data = unwrap_data(payload)
        total: Optional[int] = None

        if isinstance(data, dict):
            total_value = first_value(
                data,
                ("total", "totalCount"),
            )
            try:
                total = int(total_value)
            except (TypeError, ValueError):
                total = None

        if not page:
            break

        if total is not None and len(all_items) >= total:
            break

        if len(page) < size:
            break

        offset += size

    return all_items, raw_pages


def fetch_all(
    filter_expression: Optional[str],
    size: int,
    timeout: float,
    debug: bool,
) -> Dict[str, Any]:

    pipelines, pipeline_raw = get_all(
        LOGPIPELINES_PATH,
        filter_expression,
        size,
        timeout,
        debug,
    )

    processors, processor_raw = get_all(
        PROCESSORS_PATH,
        filter_expression,
        size,
        timeout,
        debug,
    )

    return {
        "logpipelines": pipelines,
        "processors": processors,
        "rawResponses": {
            "logpipelines": pipeline_raw,
            "processors": processor_raw,
        },
    }


# ---------------------------------------------------------------------------
# Tree
# ---------------------------------------------------------------------------

PIPELINE_ID_FIELDS = (
    "id",
    "pipelineId",
    "logAlertGroupId",
    "logalertGroupId",
)

PROCESSOR_ID_FIELDS = (
    "id",
    "processorId",
    "logAlertId",
)

PROCESSOR_PARENT_FIELDS = (
    "pipelineId",
    "logAlertGroupId",
    "logalertGroupId",
    "groupId",
    "logPipelineId",
)

NAME_FIELDS = (
    "displayName",
    "name",
    "fullName",
    "title",
)

TYPE_FIELDS = (
    "type",
    "alertType",
    "processorType",
)


def object_id(
    obj: Dict[str, Any],
    fields: Sequence[str],
) -> Optional[str]:
    value = first_value(obj, fields)

    if value is None:
        return None

    return str(value)


def object_name(
    obj: Dict[str, Any],
    fallback: str,
) -> str:
    return pretty_value(
        first_value(
            obj,
            NAME_FIELDS,
            fallback,
        )
    )


def object_type(
    obj: Dict[str, Any],
    fallback: str,
) -> str:
    return pretty_value(
        first_value(
            obj,
            TYPE_FIELDS,
            fallback,
        )
    )


def processor_parent_id(
    processor: Dict[str, Any],
) -> Optional[str]:
    value = first_value(
        processor,
        PROCESSOR_PARENT_FIELDS,
    )

    if isinstance(value, dict):
        value = first_value(
            value,
            ("id", "pipelineId", "groupId"),
        )

    if value is None:
        return None

    return str(value)


def render_tree(
    pipelines: Sequence[Dict[str, Any]],
    processors: Sequence[Dict[str, Any]],
    pipeline_id: Optional[str] = None,
) -> Tuple[str, List[List[str]], List[str]]:

    pipeline_map: Dict[str, Dict[str, Any]] = {}

    for pipeline in pipelines:
        pid = object_id(
            pipeline,
            PIPELINE_ID_FIELDS,
        )

        if pid is not None:
            pipeline_map[pid] = pipeline

    if pipeline_id is not None:
        selected = pipeline_map.get(str(pipeline_id))

        if selected is None:
            die(
                f"LogAlert Group ID {pipeline_id!r} "
                "was not found."
            )

        display_pipelines = [selected]
    else:
        display_pipelines = sorted(
            pipelines,
            key=lambda item: object_name(
                item,
                "Unnamed LogAlert Group",
            ).casefold(),
        )

    children: Dict[
        str,
        List[Dict[str, Any]]
    ] = {}

    orphan_processors: List[Dict[str, Any]] = []

    for processor in processors:
        parent = processor_parent_id(processor)

        if parent in pipeline_map:
            children.setdefault(
                parent,
                [],
            ).append(processor)
        else:
            orphan_processors.append(processor)

    for child_list in children.values():
        child_list.sort(
            key=lambda item: object_name(
                item,
                "Unnamed LogAlert",
            ).casefold()
        )

    orphan_processors.sort(
        key=lambda item: object_name(
            item,
            "Unnamed LogAlert",
        ).casefold()
    )

    lines = [
        "LogicMonitor LogAlert Groups / LogAlerts",
        f"LogAlert Groups: {len(pipelines)}",
        f"LogAlerts: {len(processors)}",
        "",
    ]

    table_rows: List[List[str]] = []

    for pipeline in display_pipelines:
        pid = (
            object_id(
                pipeline,
                PIPELINE_ID_FIELDS,
            )
            or "?"
        )

        pname = object_name(
            pipeline,
            "Unnamed LogAlert Group",
        )

        ptype = object_type(
            pipeline,
            "LogAlert Group",
        )

        query = first_value(
            pipeline,
            (
                "query",
                "alertQuery",
                "logsQuery",
                "filter",
                "condition",
            ),
            "",
        )

        lines.append(
            f"[PIPELINE] {pname} "
            f"(id={pid}, type={ptype})"
        )

        if query not in ("", None):
            lines.append(
                f"├── query: {pretty_value(query)}"
            )

        members = children.get(
            pid,
            [],
        )

        if not members:
            lines.append(
                "└── [no LogAlerts returned]"
            )

        for index, processor in enumerate(
            members
        ):
            branch = (
                "└──"
                if index == len(members) - 1
                else "├──"
            )

            processor_id = (
                object_id(
                    processor,
                    PROCESSOR_ID_FIELDS,
                )
                or "?"
            )

            processor_name = object_name(
                processor,
                "Unnamed LogAlert",
            )

            processor_type = object_type(
                processor,
                "LogAlert",
            )

            severity = first_value(
                processor,
                (
                    "severity",
                    "alertLevel",
                    "level",
                ),
                "",
            )

            lines.append(
                f"{branch} [PROCESSOR] "
                f"{processor_name} "
                f"(id={processor_id}, "
                f"type={processor_type})"
                + (
                    f" severity={pretty_value(severity)}"
                    if severity not in ("", None)
                    else ""
                )
            )

            query2 = first_value(
                processor,
                (
                    "alertQuery",
                    "query",
                    "logsQuery",
                    "condition",
                ),
                "",
            )

            prefix = (
                "    "
                if branch == "└──"
                else "│   "
            )

            if query2 not in ("", None):
                lines.append(
                    f"{prefix}└── query: "
                    f"{pretty_value(query2)}"
                )

            table_rows.append(
                [
                    "LogAlert Group",
                    pid,
                    pname,
                    "",
                    "",
                    "",
                ]
            )

            table_rows.append(
                [
                    "LogAlert",
                    processor_id,
                    pname,
                    processor_name,
                    processor_type,
                    severity,
                ]
            )

    if orphan_processors:
        lines.extend(
            [
                "",
                "[ORPHAN PROCESSORS] "
                "Parent pipeline could not be resolved:",
            ]
        )

        for index, processor in enumerate(
            orphan_processors
        ):
            branch = (
                "└──"
                if index == len(orphan_processors) - 1
                else "├──"
            )

            processor_id = (
                object_id(
                    processor,
                    PROCESSOR_ID_FIELDS,
                )
                or "?"
            )

            processor_name = object_name(
                processor,
                "Unnamed LogAlert",
            )

            parent = (
                processor_parent_id(
                    processor
                )
                or "?"
            )

            lines.append(
                f"{branch} {processor_name} "
                f"(id={processor_id}, "
                f"parent={parent})"
            )

            table_rows.append(
                [
                    "Orphan LogAlert",
                    processor_id,
                    "",
                    processor_name,
                    object_type(
                        processor,
                        "LogAlert",
                    ),
                    parent,
                ]
            )

    headers = [
        "Kind",
        "ID",
        "Pipeline",
        "Processor",
        "Processor Type",
        "Severity / Parent",
    ]

    return "\n".join(lines), table_rows, headers


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

def write_html(
    path: str,
    tree_text: str,
    rows: Sequence[Sequence[Any]],
    headers: Sequence[str],
) -> None:

    output = Path(path).expanduser()
    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    head = "".join(
        f"<th>{html_escape(str(value))}</th>"
        for value in headers
    )

    body = []

    for row in rows:
        body.append(
            "<tr>"
            + "".join(
                f"<td>{html_escape(pretty_value(value, 400))}</td>"
                for value in row
            )
            + "</tr>"
        )

    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LogicMonitor LogAlert Groups / LogAlerts</title>
<style>
body {{
  font-family: system-ui, sans-serif;
  margin: 24px;
}}
.meta {{
  color: #555;
  margin-bottom: 16px;
}}
.report {{
  overflow: auto;
  max-width: 100%;
  max-height: 75vh;
  border: 1px solid #bbb;
}}
table {{
  border-collapse: collapse;
  width: max-content;
  min-width: 100%;
}}
th, td {{
  border: 1px solid #ccc;
  padding: 6px 10px;
  text-align: left;
  white-space: nowrap;
  vertical-align: top;
}}
th {{
  position: sticky;
  top: 0;
  background: #eee;
  resize: horizontal;
  overflow: auto;
  min-width: 80px;
  cursor: col-resize;
}}
pre {{
  overflow: auto;
  padding: 12px;
  border: 1px solid #ccc;
}}
</style>
</head>
<body>
<h1>LogicMonitor LogAlert Groups / LogAlerts</h1>
<div class="meta">
Generated {html_escape(iso_now())}
· Created by {html_escape(__author__)}
· Version {html_escape(__version__)}
</div>
<pre>{html_escape(tree_text)}</pre>
<div class="report">
<table>
<thead><tr>{head}</tr></thead>
<tbody>
{"".join(body)}
</tbody>
</table>
</div>
</body>
</html>
"""

    output.write_text(
        document,
        encoding="utf-8",
    )

    print(f"Saved HTML report to {output}")


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

def write_backup(
    path: str,
    data: Dict[str, Any],
) -> None:

    output = Path(path).expanduser()
    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    document = {
        "backupFormatVersion": 1,
        "utilityVersion": __version__,
        "createdBy": __author__,
        "createdAt": iso_now(),
        "api": {
            "basePath": "/santaba/rest",
            "endpoints": {
                "logpipelines": LOGPIPELINES_PATH,
                "processors": PROCESSORS_PATH,
            },
        },
        "logpipelines": data["logpipelines"],
        "processors": data["processors"],
        "rawResponses": data["rawResponses"],
    }

    output.write_text(
        json.dumps(
            document,
            indent=2,
            ensure_ascii=False,
            default=json_default,
        ) + "\n",
        encoding="utf-8",
    )

    print(
        f"Saved backup to {output} "
        f"({len(data['logpipelines'])} LogAlert Groups, "
        f"{len(data['processors'])} LogAlerts)"
    )


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def load_json_file(path: str) -> Dict[str, Any]:
    source = Path(path).expanduser()

    if not source.is_file():
        die(f"JSON file does not exist: {source}")

    try:
        document = json.loads(
            source.read_text(
                encoding="utf-8"
            )
        )
    except (OSError, ValueError) as exc:
        die(
            f"Unable to read JSON file {source}: {exc}"
        )

    if not isinstance(document, dict):
        die(
            "The JSON root must be an object."
        )

    return document


def is_backup(document: Dict[str, Any]) -> bool:
    return (
        isinstance(
            document.get("logpipelines"),
            list,
        )
        and isinstance(
            document.get("processors"),
            list,
        )
    )


def strip_create_fields(
    source: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Remove GET/server-generated IDs and backup wrapper metadata.

    Configuration fields returned by the API are otherwise retained.
    """
    payload = dict(source)

    payload.pop("id", None)
    payload.pop("processorId", None)
    payload.pop("logAlertId", None)
    payload.pop("logAlertGroupId", None)

    return payload


def select_backup_object(
    document: Dict[str, Any],
    kind: str,
    object_id_value: str,
) -> Dict[str, Any]:

    key = (
        "logpipelines"
        if kind == "pipeline"
        else "processors"
    )

    objects = document.get(key, [])

    for item in objects:
        if not isinstance(item, dict):
            continue

        item_id = object_id(
            item,
            (
                PIPELINE_ID_FIELDS
                if kind == "pipeline"
                else PROCESSOR_ID_FIELDS
            ),
        )

        if item_id == str(object_id_value):
            return strip_create_fields(item)

    die(
        f"{kind} ID {object_id_value!r} "
        f"was not found in backup section '{key}'."
    )
    return {}


def create_one(
    kind: str,
    payload: Dict[str, Any],
    timeout: float,
    debug: bool,
) -> Any:

    path = (
        LOGPIPELINES_PATH
        if kind == "pipeline"
        else PROCESSORS_PATH
    )

    required = (
        ("name",)
        if kind == "pipeline"
        else (
            "name",
            "alertQuery",
            "alertType",
            "severity",
        )
    )

    missing = [
        field
        for field in required
        if payload.get(field) in (None, "")
    ]

    if missing:
        die(
            f"Create payload is missing required field(s): "
            + ", ".join(missing)
        )

    print(
        f"Creating {kind} with POST {path} ..."
    )

    response = api_request(
        "POST",
        path,
        payload=payload,
        timeout=timeout,
        debug=debug,
    )

    print(
        json.dumps(
            response,
            indent=2,
            ensure_ascii=False,
            default=json_default,
        )
    )

    return response


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------

def extract_created_id(response: Any) -> Optional[str]:
    """
    Extract the newly created resource ID from common LogicMonitor response
    wrappers.
    """
    pending: List[Any] = [response]

    while pending:
        current = pending.pop(0)

        if isinstance(current, dict):
            value = first_value(
                current,
                (
                    "id",
                    "pipelineId",
                    "processorId",
                    "logAlertId",
                    "logAlertGroupId",
                ),
            )

            if value is not None:
                return str(value)

            for key in (
                "data",
                "item",
                "resource",
                "result",
            ):
                if key in current:
                    pending.append(current[key])

        elif isinstance(current, list):
            pending.extend(current)

    return None


def restore_backup(
    path: str,
    timeout: float,
    debug: bool,
    results_path: Optional[str],
    partition: str,
) -> int:

    document = load_json_file(path)

    if not is_backup(document):
        die(
            "Restore requires a backup containing both "
            "'logpipelines' and 'processors' arrays."
        )

    pipelines = document["logpipelines"]
    processors = document["processors"]

    print(
        f"Starting restore from {path}: "
        f"{len(pipelines)} LogAlert Groups, "
        f"{len(processors)} LogAlerts."
    )

    print(
        "WARNING: --restore is CREATE ONLY. "
        "It does not delete existing configuration."
    )

    pipeline_id_map: Dict[str, str] = {}

    results: Dict[str, Any] = {
        "restoreFormatVersion": 1,
        "utilityVersion": __version__,
        "createdBy": __author__,
        "createdAt": iso_now(),
        "sourceBackup": str(path),
        "pipelineIdMap": {},
        "pipelines": [],
        "processors": [],
        "summary": {
            "pipelinesTotal": len(pipelines),
            "pipelinesCreated": 0,
            "pipelinesFailed": 0,
            "processorsTotal": len(processors),
            "processorsCreated": 0,
            "processorsFailed": 0,
            "processorsSkipped": 0,
        },
    }

    print("\nPhase 1/2: Creating LogAlert Groups...")

    for index, pipeline in enumerate(
        pipelines,
        start=1,
    ):

        if not isinstance(pipeline, dict):
            results["summary"]["pipelinesFailed"] += 1
            results["pipelines"].append({
                "index": index,
                "status": "failed",
                "error": "Pipeline is not a JSON object.",
            })
            continue

        old_id = object_id(
            pipeline,
            PIPELINE_ID_FIELDS,
        )

        if old_id is None:
            results["summary"]["pipelinesFailed"] += 1
            results["pipelines"].append({
                "index": index,
                "status": "failed",
                "error": "Pipeline has no ID.",
            })
            continue

        payload = strip_create_fields(
            pipeline
        )

        # Current LogAlert Group creation requires explicit partition
        # scoping. Older GET backups may omit this property.
        if not payload.get("partitions"):
            payload["partitions"] = [partition]

        try:
            response = create_one(
                "pipeline",
                payload,
                timeout,
                debug,
            )

            new_id = extract_created_id(
                response
            )

            if new_id is None:
                raise RuntimeError(
                    "POST succeeded but no new pipeline ID "
                    "could be extracted from the API response."
                )

            pipeline_id_map[
                str(old_id)
            ] = str(new_id)

            results["pipelineIdMap"][
                str(old_id)
            ] = str(new_id)

            results["summary"][
                "pipelinesCreated"
            ] += 1

            results["pipelines"].append({
                "index": index,
                "oldId": str(old_id),
                "newId": str(new_id),
                "name": first_value(
                    pipeline,
                    NAME_FIELDS,
                    "",
                ),
                "status": "created",
                "response": response,
            })

            print(
                f"[{index}/{len(pipelines)}] "
                f"CREATED pipeline "
                f"{old_id} -> {new_id}: "
                f"{first_value(pipeline, NAME_FIELDS, '')}"
            )

        except Exception as exc:
            results["summary"][
                "pipelinesFailed"
            ] += 1

            results["pipelines"].append({
                "index": index,
                "oldId": str(old_id),
                "name": first_value(
                    pipeline,
                    NAME_FIELDS,
                    "",
                ),
                "status": "failed",
                "error": str(exc),
            })

            print(
                f"[{index}/{len(pipelines)}] "
                f"FAILED pipeline {old_id}: {exc}"
            )

    print("\nPhase 2/2: Creating LogAlerts...")

    for index, processor in enumerate(
        processors,
        start=1,
    ):

        if not isinstance(processor, dict):
            results["summary"][
                "processorsFailed"
            ] += 1

            results["processors"].append({
                "index": index,
                "status": "failed",
                "error": "Processor is not a JSON object.",
            })

            continue

        old_id = object_id(
            processor,
            PROCESSOR_ID_FIELDS,
        )

        old_pipeline_id = processor_parent_id(
            processor
        )

        if old_id is None:
            results["summary"][
                "processorsFailed"
            ] += 1

            results["processors"].append({
                "index": index,
                "status": "failed",
                "error": "Processor has no ID.",
            })

            continue

        if old_pipeline_id is None:
            results["summary"][
                "processorsFailed"
            ] += 1

            results["processors"].append({
                "index": index,
                "oldId": str(old_id),
                "status": "failed",
                "error": "Processor has no pipelineId.",
            })

            print(
                f"[{index}/{len(processors)}] "
                f"FAILED processor {old_id}: "
                "no pipelineId"
            )
            continue

        new_pipeline_id = pipeline_id_map.get(
            str(old_pipeline_id)
        )

        if new_pipeline_id is None:
            results["summary"][
                "processorsSkipped"
            ] += 1

            results["processors"].append({
                "index": index,
                "oldId": str(old_id),
                "oldPipelineId": str(old_pipeline_id),
                "status": "skipped",
                "error": (
                    "Parent pipeline was not created successfully."
                ),
            })

            print(
                f"[{index}/{len(processors)}] "
                f"SKIPPED processor {old_id}: "
                f"pipeline {old_pipeline_id} "
                "has no new ID"
            )
            continue

        payload = strip_create_fields(
            processor
        )

        # CRITICAL: rewrite the old pipeline ID to the new destination ID.
        payload["pipelineId"] = new_pipeline_id

        try:
            response = create_one(
                "processor",
                payload,
                timeout,
                debug,
            )

            new_id = extract_created_id(
                response
            )

            results["summary"][
                "processorsCreated"
            ] += 1

            results["processors"].append({
                "index": index,
                "oldId": str(old_id),
                "newId": (
                    str(new_id)
                    if new_id is not None
                    else None
                ),
                "oldPipelineId": str(old_pipeline_id),
                "newPipelineId": str(new_pipeline_id),
                "name": first_value(
                    processor,
                    NAME_FIELDS,
                    "",
                ),
                "status": "created",
                "response": response,
            })

            print(
                f"[{index}/{len(processors)}] "
                f"CREATED processor {old_id}"
                + (
                    f" -> {new_id}"
                    if new_id is not None
                    else ""
                )
                + f", pipeline "
                f"{old_pipeline_id} -> "
                f"{new_pipeline_id}: "
                f"{first_value(processor, NAME_FIELDS, '')}"
            )

        except Exception as exc:
            results["summary"][
                "processorsFailed"
            ] += 1

            results["processors"].append({
                "index": index,
                "oldId": str(old_id),
                "oldPipelineId": str(old_pipeline_id),
                "newPipelineId": str(new_pipeline_id),
                "name": first_value(
                    processor,
                    NAME_FIELDS,
                    "",
                ),
                "status": "failed",
                "error": str(exc),
            })

            print(
                f"[{index}/{len(processors)}] "
                f"FAILED processor {old_id}: {exc}"
            )

    print("\nRestore summary:")
    print(
        f"  Pipelines: "
        f"{results['summary']['pipelinesCreated']} created, "
        f"{results['summary']['pipelinesFailed']} failed"
    )
    print(
        f"  Processors: "
        f"{results['summary']['processorsCreated']} created, "
        f"{results['summary']['processorsFailed']} failed, "
        f"{results['summary']['processorsSkipped']} skipped"
    )

    if results_path:
        output = Path(
            results_path
        ).expanduser()

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output.write_text(
            json.dumps(
                results,
                indent=2,
                ensure_ascii=False,
                default=json_default,
            ) + "\n",
            encoding="utf-8",
        )

        print(
            f"Restore results saved to {output}"
        )

    if (
        results["summary"]["pipelinesFailed"]
        or results["summary"]["processorsFailed"]
        or results["summary"]["processorsSkipped"]
    ):
        return 1

    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(
    argv: Optional[Sequence[str]] = None,
) -> int:

    args = parse_args(argv)

    # No arguments: show help without requiring credentials.
    if (
        argv is None
        and len(sys.argv) == 1
    ):
        parse_args(["--help"])
        return 0

    if (
        args.create_id
        and not args.create
    ):
        die(
            "--create-id requires --create."
        )

    if (
        args.restore_results
        and not args.restore
    ):
        die(
            "--restore-results requires --restore."
        )

    if args.restore and (
        args.create
        or args.create_id
        or args.create_kind
        or args.show_tree
        or args.pipeline_id
        or args.filter
        or args.html
        or args.raw
    ):
        die(
            "--restore cannot be combined with "
            "create, show-tree, pipeline-id, filter, "
            "html, or raw options."
        )

    if args.html and not args.show_tree:
        die(
            "--html requires --show-tree."
        )

    if args.pipeline_id and not args.show_tree:
        die(
            "--pipeline-id requires --show-tree."
        )

    load_credentials(
        args.creds_file
    )
    require_credentials()

    if args.restore:
        return restore_backup(
            args.restore,
            timeout=args.timeout,
            debug=args.debug,
            results_path=args.restore_results,
            partition=args.partition,
        )

    if args.create:
        document = load_json_file(
            args.create
        )

        if is_backup(document):
            if args.create_kind not in (
                "pipeline",
                "processor",
            ):
                die(
                    "When --create uses a backup, "
                    "--create-kind is required."
                )

            if args.create_id is None:
                die(
                    "When --create uses a backup, "
                    "--create-id is required."
                )

            payload = select_backup_object(
                document,
                args.create_kind,
                args.create_id,
            )

            create_one(
                args.create_kind,
                payload,
                timeout=args.timeout,
                debug=args.debug,
            )

        else:
            kind = args.create_kind

            if kind is None:
                kind = document.get("kind")

            payload = document.get(
                "payload"
            )

            if payload is None:
                payload = {
                    key: value
                    for key, value in document.items()
                    if key not in (
                        "kind",
                        "payload",
                    )
                }

            if kind not in (
                "pipeline",
                "processor",
            ):
                die(
                    "A standalone create JSON requires "
                    "--create-kind pipeline|processor, "
                    "or a top-level 'kind' field."
                )

            if not isinstance(payload, dict):
                die(
                    "Create payload must be a JSON object."
                )

            if args.create_id:
                die(
                    "--create-id can only be used with a backup."
                )

            if kind == "pipeline" and not payload.get("partitions"):
                payload["partitions"] = [args.partition]

            create_one(
                kind,
                payload,
                timeout=args.timeout,
                debug=args.debug,
            )

        return 0

    if args.backup:
        data = fetch_all(
            filter_expression=args.filter,
            size=args.size,
            timeout=args.timeout,
            debug=args.debug,
        )

        write_backup(
            args.backup,
            data,
        )

        if args.raw:
            print(
                json.dumps(
                    data,
                    indent=2,
                    ensure_ascii=False,
                    default=json_default,
                )
            )

        return 0

    if args.show_tree:
        data = fetch_all(
            filter_expression=args.filter,
            size=args.size,
            timeout=args.timeout,
            debug=args.debug,
        )

        tree_text, rows, headers = render_tree(
            data["logpipelines"],
            data["processors"],
            pipeline_id=args.pipeline_id,
        )

        print(tree_text)
        print()
        print(
            tabulate(
                rows,
                headers=headers,
                tablefmt="grid",
            )
        )

        if args.raw:
            print(
                "\nRaw JSON:"
            )
            print(
                json.dumps(
                    {
                        "logpipelines":
                            data["logpipelines"],
                        "processors":
                            data["processors"],
                    },
                    indent=2,
                    ensure_ascii=False,
                    default=json_default,
                )
            )

        if args.html:
            write_html(
                args.html,
                tree_text,
                rows,
                headers,
            )

        return 0

    parse_args(["--help"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# EOF
