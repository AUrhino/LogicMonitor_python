#!/usr/bin/env python3
"""
Get-LMAlerts.py
------------------
LogicMonitor Alerts CLI

Modes:
  1) Capture account-wide alerts
  2) Capture alerts for a specific device
  3) Fetch a single alert by alert ID

Requirements:
- Python 3.x
- requests, python-dotenv
- optional: tabulate
- .env file with:
    ACCESS_ID=your_access_id
    ACCESS_KEY=your_access_key
    COMPANY=your_company_name
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv


__version__ = "1.0.6"

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

try:
    from tabulate import tabulate
except ImportError:
    tabulate = None


ACCESS_KEY = os.getenv("ACCESS_KEY", "")
ACCESS_ID = os.getenv("ACCESS_ID", "")
COMPANY = os.getenv("COMPANY", "")

BASE_URL = f"https://{COMPANY}.logicmonitor.com/santaba/rest"
DEFAULT_OUT_DIR = "output"
DEFAULT_PAGE_SIZE = 200
DEFAULT_PREVIEW_LIMIT = 50
REQUEST_TIMEOUT = 30
DEBUG = False
DISPLAY_TIMEZONE_NAME = "Australia/Sydney"

if ZoneInfo is not None:
    try:
        DISPLAY_TIMEZONE = ZoneInfo(DISPLAY_TIMEZONE_NAME)
    except Exception:
        DISPLAY_TIMEZONE = timezone(timedelta(hours=11))
else:
    DISPLAY_TIMEZONE = timezone(timedelta(hours=11))

PREVIEW_REQUIRED_FIELDS = [
    "id",
    "monitorObjectId",
    "internalId",
    "monitorObjectName",
    "resourceTemplateName",
    "instanceName",
    "dataPointName",
    "severity",
    "startEpoch",
    "endEpoch",
    "sdted",
    "SDT",
    "cleared",
    "ruleId",
    "chainId",
    "receivedList",
    "inAlerting",
    "suppressor",
    "suppressDesc",
    "alertExternalTicketUrl",
    "dependencyRoutingState",
    "dependencyRole",
    "externalTicketId",
    "dependencyMessage",
    "dependentAlertCount",
    "acked",
    "detailMessage",
]

SINGLE_ALERT_REQUIRED_FIELDS = [
    "id",
    "monitorObjectName",
    "resourceTemplateName",
    "instanceName",
    "dataPointName",
    "severity",
    "startEpoch",
    "endEpoch",
    "sdted",
    "SDT",
    "cleared",
    "acked",
    "ackedBy",
    "rule",
    "chain",
    "ruleId",
    "chainId",
    "receivedList",
    "inAlerting",
    "suppressor",
    "suppressDesc",
    "alertExternalTicketUrl",
    "dependencyRoutingState",
    "dependencyRole",
    "externalTicketId",
    "dependencyMessage",
    "dependentAlertCount",
    "detailMessage",
]


class LMAPIError(RuntimeError):
    """Raised when the LogicMonitor API returns an error or invalid response."""


def validate_env() -> None:
    missing = [
        name
        for name, value in {
            "ACCESS_ID": ACCESS_ID,
            "ACCESS_KEY": ACCESS_KEY,
            "COMPANY": COMPANY,
        }.items()
        if not value
    ]
    if missing:
        raise SystemExit(
            "Missing required environment variables in .env: "
            + ", ".join(missing)
        )


def load_credentials(env_file: str) -> None:
    """Load credentials from the selected dotenv file, overriding inherited env."""
    global ACCESS_KEY, ACCESS_ID, COMPANY, BASE_URL
    if not os.path.isfile(env_file):
        raise SystemExit(f"Credentials file not found: {env_file}")
    load_dotenv(env_file, override=True)
    ACCESS_KEY = os.getenv("ACCESS_KEY", "")
    ACCESS_ID = os.getenv("ACCESS_ID", "")
    COMPANY = os.getenv("COMPANY", "")
    BASE_URL = f"https://{COMPANY}.logicmonitor.com/santaba/rest"
    validate_env()


def positive_int(value: str) -> int:
    ivalue = int(value)
    if ivalue < 1:
        raise argparse.ArgumentTypeError("Value must be >= 1")
    return ivalue


def normalize_epoch_to_seconds(epoch_value: Any) -> Optional[int]:
    """
    Normalize epoch values that may be provided in:
    - seconds (10 digits)
    - milliseconds (13 digits)
    - microseconds
    - nanoseconds
    """
    if epoch_value in (None, ""):
        return None

    try:
        value = int(float(str(epoch_value).strip()))
    except (TypeError, ValueError):
        return None

    abs_value = abs(value)

    if abs_value >= 1_000_000_000_000_000_000:
        return value // 1_000_000_000
    if abs_value >= 1_000_000_000_000_000:
        return value // 1_000_000
    if abs_value >= 1_000_000_000_000:
        return value // 1_000
    return value


def days_ago_to_epoch_seconds(days: int) -> int:
    return int(time.time()) - (days * 86400)


def hours_ago_to_epoch_seconds(hours: int) -> int:
    return int(time.time()) - (hours * 3600)


def format_gmt_offset(dt: datetime) -> str:
    offset = dt.utcoffset()
    if offset is None:
        return "GMT+00:00"

    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    total_minutes = abs(total_minutes)
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"GMT{sign}{hours:02d}:{minutes:02d}"


def epoch_to_display_date(epoch_value: Any) -> str:
    epoch_seconds = normalize_epoch_to_seconds(epoch_value)
    if epoch_seconds is None:
        return ""

    try:
        dt = datetime.fromtimestamp(epoch_seconds, tz=DISPLAY_TIMEZONE)
    except (OSError, OverflowError, ValueError):
        return ""

    hour_12 = dt.hour % 12 or 12
    am_pm = "am" if dt.hour < 12 else "pm"
    gmt_offset = format_gmt_offset(dt)

    return (
        f"{dt.strftime('%A')} "
        f"{dt.day} "
        f"{dt.strftime('%B')} "
        f"{dt.year} "
        f"at {hour_12}:{dt.minute:02d}:{dt.second:02d} "
        f"{am_pm} "
        f"{gmt_offset}"
    )


def seconds_to_duration_string(total_seconds: int) -> str:
    if total_seconds < 0:
        return ""

    days = total_seconds // 86400
    remainder = total_seconds % 86400
    hours = remainder // 3600
    remainder %= 3600
    minutes = remainder // 60
    seconds = remainder % 60

    parts: List[str] = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")

    return " ".join(parts)


def alert_duration_value(alert: Dict[str, Any]) -> str:
    start_seconds = normalize_epoch_to_seconds(alert.get("startEpoch"))
    if start_seconds is None:
        return ""

    end_seconds = normalize_epoch_to_seconds(alert.get("endEpoch"))
    if end_seconds is None:
        end_seconds = int(time.time())

    duration_seconds = end_seconds - start_seconds
    return seconds_to_duration_string(duration_seconds)


def filter_alerts_since_days(
    alerts: List[Dict[str, Any]], days_ago: Optional[int]
) -> List[Dict[str, Any]]:
    if days_ago is None:
        return alerts

    cutoff_seconds = days_ago_to_epoch_seconds(days_ago)
    filtered: List[Dict[str, Any]] = []

    for alert in alerts:
        alert_start_seconds = normalize_epoch_to_seconds(alert.get("startEpoch"))
        if alert_start_seconds is None:
            continue
        if alert_start_seconds >= cutoff_seconds:
            filtered.append(alert)

    return filtered


def filter_alerts_since_hours(alerts: List[Dict[str, Any]], hours_ago: Optional[int]) -> List[Dict[str, Any]]:
    if hours_ago is None:
        return alerts
    cutoff_seconds = int(time.time()) - hours_ago * 3600
    return [a for a in alerts if (normalize_epoch_to_seconds(a.get("startEpoch")) or 0) >= cutoff_seconds]


def filter_alerts_by_id(alerts: List[Dict[str, Any]], alert_id: Optional[str]) -> List[Dict[str, Any]]:
    if not alert_id:
        return alerts
    return [a for a in alerts if str(a.get("id", "")) == alert_id]


def alert_sdt_value(alert: Dict[str, Any]) -> str:
    sdted = alert.get("sdted")
    if isinstance(sdted, bool):
        return "True" if sdted else "False"
    if sdted not in (None, ""):
        return str(sdted)

    active_sdt = alert.get("SDT")
    if isinstance(active_sdt, dict):
        return "True" if active_sdt else "False"
    if active_sdt not in (None, "", [], {}):
        return "True"

    return ""


def normalize_whitespace(value: str) -> str:
    return " ".join(value.split())


def compact_message_value(detail_message: Any) -> str:
    if detail_message is None:
        return ""

    if isinstance(detail_message, dict):
        subject = detail_message.get("subject")
        body = detail_message.get("body")

        if subject not in (None, ""):
            return normalize_whitespace(str(subject))
        if body not in (None, ""):
            return normalize_whitespace(str(body))

        return normalize_whitespace(
            json.dumps(detail_message, ensure_ascii=False, separators=(",", ":"))
        )

    if isinstance(detail_message, list):
        return normalize_whitespace(
            json.dumps(detail_message, ensure_ascii=False, separators=(",", ":"))
        )

    return normalize_whitespace(str(detail_message))


def full_message_value(detail_message: Any) -> str:
    if detail_message is None:
        return ""

    if isinstance(detail_message, dict):
        subject = detail_message.get("subject")
        body = detail_message.get("body")
        parts: List[str] = []

        if subject not in (None, ""):
            parts.append(f"Subject: {subject}")
        if body not in (None, ""):
            parts.append(f"Body:\n{body}")

        if parts:
            return "\n".join(parts)

        return json.dumps(detail_message, indent=2, ensure_ascii=False)

    if isinstance(detail_message, list):
        return json.dumps(detail_message, indent=2, ensure_ascii=False)

    return str(detail_message)


def message_value_for_table(detail_message: Any, include_full_body: bool = False) -> str:
    if include_full_body:
        return full_message_value(detail_message)
    return compact_message_value(detail_message)


def pretty_message_value(detail_message: Any) -> str:
    if detail_message is None:
        return ""

    if isinstance(detail_message, (dict, list)):
        return json.dumps(detail_message, indent=2, ensure_ascii=False)

    return str(detail_message)


def ensure_required_fields(
    fields: Optional[str], required_fields: List[str]
) -> Optional[str]:
    if not fields:
        return fields

    merged: List[str] = []
    seen_lower = set()

    for part in fields.split(","):
        value = part.strip()
        if value and value.lower() not in seen_lower:
            merged.append(value)
            seen_lower.add(value.lower())

    for field_name in required_fields:
        if field_name.lower() not in seen_lower:
            merged.append(field_name)
            seen_lower.add(field_name.lower())

    return ",".join(merged)


def generate_auth_headers(
    http_verb: str, resource_path: str, data: str = ""
) -> Dict[str, str]:
    """
    Generate LogicMonitor API authentication headers.
    """
    epoch = str(int(time.time() * 1000))
    request_vars = http_verb + epoch + data + resource_path
    hmac_hash = hmac.new(
        ACCESS_KEY.encode("utf-8"),
        msg=request_vars.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    signature = base64.b64encode(hmac_hash.encode("utf-8")).decode("utf-8")
    auth = f"LMv1 {ACCESS_ID}:{signature}:{epoch}"
    return {
        "Content-Type": "application/json",
        "Authorization": auth,
    }


def api_get(
    resource_path: str, params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Perform a GET request to the LogicMonitor API.
    """
    url = BASE_URL + resource_path
    headers = generate_auth_headers("GET", resource_path)

    if DEBUG:
        print(f"DEBUG: GET {url}", file=sys.stderr)
        print(f"DEBUG: params={params!r}", file=sys.stderr)

    try:
        response = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise LMAPIError(f"Request failed for {resource_path}: {exc}") from exc

    if not response.ok:
        if DEBUG:
            print(f"DEBUG: response_status={response.status_code}", file=sys.stderr)
            print(f"DEBUG: response_body={response.text}", file=sys.stderr)
        raise LMAPIError(
            f"GET {resource_path} failed with {response.status_code}: {response.text}"
        )

    try:
        if DEBUG:
            print(f"DEBUG: response_status={response.status_code}", file=sys.stderr)
        return response.json()
    except ValueError as exc:
        raise LMAPIError(f"GET {resource_path} did not return valid JSON.") from exc


def extract_data(payload: Dict[str, Any]) -> Any:
    """
    LogicMonitor responses are commonly wrapped as {"data": ...}.
    Fall back to the original payload if not wrapped.
    """
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


def ensure_out_dir(out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)


def sanitize_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", value)


def save_json(out_dir: str, filename: str, payload: Any) -> None:
    ensure_out_dir(out_dir)
    path = os.path.join(out_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"Saved: {path}")


def save_text(out_dir: str, filename: str, content: str) -> None:
    ensure_out_dir(out_dir)
    path = os.path.join(out_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content.rstrip() + "\n")
    print(f"Saved: {path}")


def render_ascii_grid(rows: List[List[Any]], headers: List[str]) -> str:
    prepared_headers = ["" if h is None else str(h) for h in headers]
    prepared_rows = [
        ["" if cell is None else str(cell) for cell in row]
        for row in rows
    ]

    def split_lines(value: str) -> List[str]:
        lines = value.splitlines()
        return lines if lines else [""]

    widths = [0] * len(prepared_headers)

    for idx, header in enumerate(prepared_headers):
        widths[idx] = max(widths[idx], max(len(line) for line in split_lines(header)))

    for row in prepared_rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], max(len(line) for line in split_lines(cell)))

    def border(fill: str) -> str:
        return "+" + "+".join((fill * (width + 2)) for width in widths) + "+"

    def render_row_multiline(row: List[str]) -> List[str]:
        split_row = [split_lines(cell) for cell in row]
        height = max(len(cell_lines) for cell_lines in split_row)
        rendered_lines: List[str] = []

        for line_index in range(height):
            parts = []
            for col_index, cell_lines in enumerate(split_row):
                value = cell_lines[line_index] if line_index < len(cell_lines) else ""
                parts.append(" " + value.ljust(widths[col_index]) + " ")
            rendered_lines.append("|" + "|".join(parts) + "|")

        return rendered_lines

    lines: List[str] = [border("-")]
    lines.extend(render_row_multiline(prepared_headers))
    lines.append(border("="))

    for row in prepared_rows:
        lines.extend(render_row_multiline(row))
        lines.append(border("-"))

    return "\n".join(lines)


def render_table(data: List[List[Any]], headers: List[str], title: str = "") -> str:
    lines: List[str] = []

    if title:
        lines.append("=" * 155)
        lines.append(title)
        lines.append("=" * 155)

    if not data:
        lines.append("(no data)")
        return "\n".join(lines)

    str_rows = [[("" if cell is None else str(cell)) for cell in row] for row in data]

    if tabulate:
        table_text = tabulate(str_rows, headers=headers, tablefmt="grid")
    else:
        table_text = render_ascii_grid(str_rows, headers)

    lines.append(table_text)
    return "\n".join(lines)


def print_report(report_text: str) -> None:
    print(report_text)


def paged_get_items(
    resource_path: str,
    base_params: Optional[Dict[str, Any]] = None,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Fetch all items from a paginated LM endpoint that uses size/offset.
    Returns: (all_items, last_raw_response)
    """
    all_items: List[Dict[str, Any]] = []
    offset = 0
    last_resp: Dict[str, Any] = {}

    while True:
        params = dict(base_params or {})
        params["size"] = page_size
        params["offset"] = offset

        resp = api_get(resource_path, params=params)
        last_resp = resp

        data = extract_data(resp)
        if not isinstance(data, dict):
            break

        items = data.get("items", [])
        if not isinstance(items, list):
            break

        # The alerts endpoint can return a negative `total` when it cannot
        # calculate an exact count (for example, -201 for a 200-row page).
        # Treat that as unknown and continue until a short page arrives.
        page_items = [item for item in items if isinstance(item, dict)]
        all_items.extend(page_items)

        total = data.get("total")
        offset += len(items)
        if len(items) < page_size:
            break
        if isinstance(total, int) and total > 0 and offset >= total:
            break

    return all_items, last_resp


def format_alert_rows(
    alerts: List[Dict[str, Any]],
    limit: int = DEFAULT_PREVIEW_LIMIT,
    include_full_message_in_table: bool = False,
) -> List[List[Any]]:
    rows: List[List[Any]] = []
    for alert in alerts[:limit]:
        start_epoch = alert.get("startEpoch")
        rows.append(
            [
                alert.get("id"),
                alert.get("monitorObjectId"),
                alert.get("internalId"),
                alert.get("monitorObjectName"),
                alert.get("resourceTemplateName"),
                alert.get("instanceName"),
                alert.get("dataPointName"),
                alert.get("severity"),
                epoch_to_display_date(start_epoch),
                alert_duration_value(alert),
                alert_sdt_value(alert),
                alert.get("cleared"),
                alert.get("acked"),
                alert.get("ruleId"),
                alert.get("chainId"),
                alert.get("receivedList"),
                alert.get("inAlerting"),
                alert.get("suppressor"),
                alert.get("suppressDesc"),
                alert.get("alertExternalTicketUrl"),
                alert.get("dependencyRoutingState"),
                alert.get("dependencyRole"),
                alert.get("externalTicketId"),
                alert.get("dependencyMessage"),
                alert.get("dependentAlertCount"),
                message_value_for_table(
                    alert.get("detailMessage"),
                    include_full_body=include_full_message_in_table,
                ),
            ]
        )
    return rows


def build_alert_preview_report(
    alerts: List[Dict[str, Any]],
    title: str,
    include_full_message_in_table: bool = False,
    verbose: bool = False,
) -> str:
    if verbose:
        field_names = list(dict.fromkeys(
            field_name
            for alert in alerts[:DEFAULT_PREVIEW_LIMIT]
            for field_name in alert
        ))
        rows = [
            [
                json.dumps(alert.get(field_name), ensure_ascii=False)
                if isinstance(alert.get(field_name), (dict, list))
                else alert.get(field_name, "")
                for field_name in field_names
            ]
            for alert in alerts[:DEFAULT_PREVIEW_LIMIT]
        ]
        report_text = render_table(rows, field_names, title)
        if len(alerts) > DEFAULT_PREVIEW_LIMIT:
            report_text += f"\n\nShowing first {DEFAULT_PREVIEW_LIMIT} of {len(alerts)} alerts."
        return report_text

    headers = [
        "Alert ID",
        "Device ID",
        "Internal ID",
        "Object",
        "DataSource",
        "Instance",
        "DataPoint",
        "Severity",
        "Date",
        "Duration",
        "SDT",
        "Cleared",
        "Acked",
        "Rule ID",
        "Chain ID",
        "Received List",
        "In Alerting",
        "Suppressor",
        "Suppress Description",
        "External Ticket URL",
        "Dependency Routing State",
        "Dependency Role",
        "External Ticket ID",
        "Dependency Message",
        "Dependent Alert Count",
        "Message",
    ]

    report_text = render_table(
        format_alert_rows(
            alerts,
            include_full_message_in_table=include_full_message_in_table,
        ),
        headers,
        title,
    )

    if len(alerts) > DEFAULT_PREVIEW_LIMIT:
        report_text += (
            f"\n\nShowing first {DEFAULT_PREVIEW_LIMIT} of {len(alerts)} alerts."
        )

    return report_text


def build_single_alert_report(
    alert: Dict[str, Any],
    include_full_message_in_table: bool = False,
    include_detail_section: bool = True,
    verbose: bool = False,
) -> str:
    start_epoch = alert.get("startEpoch")
    detail_message = alert.get("detailMessage")

    if verbose:
        summary_rows = [
            [
                field_name,
                json.dumps(value, ensure_ascii=False)
                if isinstance(value, (dict, list))
                else value,
            ]
            for field_name, value in alert.items()
        ]
    else:
        summary_rows = [
        ["Alert ID", alert.get("id")],
        ["Object", alert.get("monitorObjectName")],
        ["DataSource", alert.get("resourceTemplateName")],
        ["Instance", alert.get("instanceName")],
        ["DataPoint", alert.get("dataPointName")],
        ["Severity", alert.get("severity")],
        ["Date", epoch_to_display_date(start_epoch)],
        ["Duration", alert_duration_value(alert)],
        ["SDT", alert_sdt_value(alert)],
        ["EndEpoch", alert.get("endEpoch")],
        ["Cleared", alert.get("cleared")],
        ["Acked", alert.get("acked")],
        ["Acked By", alert.get("ackedBy")],
        ["Rule", alert.get("rule")],
        ["Chain", alert.get("chain")],
        ["Rule ID", alert.get("ruleId")],
        ["Chain ID", alert.get("chainId")],
        ["Received List", alert.get("receivedList")],
        ["In Alerting", alert.get("inAlerting")],
        ["Suppressor", alert.get("suppressor")],
        ["Suppress Description", alert.get("suppressDesc")],
        ["External Ticket URL", alert.get("alertExternalTicketUrl")],
        ["Dependency Routing State", alert.get("dependencyRoutingState")],
        ["Dependency Role", alert.get("dependencyRole")],
        ["External Ticket ID", alert.get("externalTicketId")],
        ["Dependency Message", alert.get("dependencyMessage")],
        ["Dependent Alert Count", alert.get("dependentAlertCount")],
        [
            "Message",
            message_value_for_table(
                detail_message,
                include_full_body=include_full_message_in_table,
            ),
        ],
        ]

    report_text = render_table(summary_rows, ["Field", "Value"], "Alert Summary")

    if include_detail_section:
        pretty_message = pretty_message_value(detail_message)
        if pretty_message:
            report_text += f"\n\nDetail Message:\n{pretty_message}"

    return report_text


def get_alerts_accountwide(
    lm_filter: Optional[str] = None,
    fields: Optional[str] = None,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> List[Dict[str, Any]]:
    """
    Capture alerts account-wide.
    """
    params: Dict[str, Any] = {}
    if lm_filter:
        params["filter"] = lm_filter
    params["fields"] = ensure_required_fields(fields, PREVIEW_REQUIRED_FIELDS)

    alerts, _ = paged_get_items("/alert/alerts", base_params=params, page_size=page_size)
    return alerts


def get_alerts_for_device(
    device_id: int,
    lm_filter: Optional[str] = None,
    fields: Optional[str] = None,
    custom_columns: Optional[str] = None,
    need_message: bool = False,
    bound: str = "instances",
    page_size: int = DEFAULT_PAGE_SIZE,
    start: Optional[int] = None,
    end: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Capture alerts for a specific device.
    """
    params: Dict[str, Any] = {
        "needMessage": str(need_message).lower(),
        "bound": bound,
    }

    if lm_filter:
        params["filter"] = lm_filter
    params["fields"] = ensure_required_fields(fields, PREVIEW_REQUIRED_FIELDS)
    if custom_columns:
        params["customColumns"] = custom_columns
    if start is not None:
        params["start"] = start
    if end is not None:
        params["end"] = end

    alerts, _ = paged_get_items(
        f"/device/devices/{device_id}/alerts",
        base_params=params,
        page_size=page_size,
    )
    return alerts


def get_alert_by_id(
    alert_id: str,
    need_message: bool = False,
    fields: Optional[str] = None,
    custom_columns: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Fetch a single alert by ID.
    """
    params: Dict[str, Any] = {
        "needMessage": str(need_message).lower(),
    }
    params["fields"] = ensure_required_fields(fields, SINGLE_ALERT_REQUIRED_FIELDS)
    if custom_columns:
        params["customColumns"] = custom_columns

    resp = api_get(f"/alert/alerts/{alert_id}", params=params)
    data = extract_data(resp)

    if not isinstance(data, dict):
        raise LMAPIError(f"Unexpected alert payload for alert ID {alert_id}: {data}")

    return data


def build_parser() -> argparse.ArgumentParser:
    main_examples = """Examples:
  Show this help:
    python Get-LMAlerts.py --help

  Show the installed script version:
    python Get-LMAlerts.py --version

  Account-wide alerts:
    python Get-LMAlerts.py account
    python Get-LMAlerts.py account --filter "cleared:false"
    python Get-LMAlerts.py account --fields "id,severity,monitorObjectName"
    python Get-LMAlerts.py account --days-ago 1
    python Get-LMAlerts.py account --days-ago 7 --filter "cleared:false"
    python Get-LMAlerts.py account --hours-ago 6
    python Get-LMAlerts.py account --alert-id DS267
    python Get-LMAlerts.py account --hours-ago 24 --alert-id DS267 --creds ./production.env
    python Get-LMAlerts.py account --save-table
    python Get-LMAlerts.py account --page-size 100 --output-dir ./output
    python Get-LMAlerts.py account --debug --verbose

  Alerts for a specific device:
    python Get-LMAlerts.py device --device-id 123
    python Get-LMAlerts.py device --device-id 123 --debug
    python Get-LMAlerts.py device --device-id 123 --need-message
    python Get-LMAlerts.py device --device-id 123 --filter "severity:>=3"
    python Get-LMAlerts.py device --device-id 123 --days-ago 7
    python Get-LMAlerts.py device --device-id 123 --hours-ago 12 --alert-id DS267
    python Get-LMAlerts.py device --device-id 123 --days-ago 14 --need-message --save-table
    python Get-LMAlerts.py device --device-id 123 --start 1773581054 --end 1773667454
    python Get-LMAlerts.py device --device-id 123 --fields "id,severity,monitorObjectName"
    python Get-LMAlerts.py device --device-id 123 --custom-columns "property=value"
    python Get-LMAlerts.py device --device-id 123 --bound instances --page-size 100 --output-dir ./output
    python Get-LMAlerts.py device --device-id 123 --debug --verbose

  Single alert by ID:
    python Get-LMAlerts.py alert --alert-id DS267
    python Get-LMAlerts.py alert --alert-id DS267 --need-message
    python Get-LMAlerts.py alert --alert-id DS267 --need-message --save-table
    python Get-LMAlerts.py alert --alert-id DS267 --fields "id,severity,monitorObjectName"
    python Get-LMAlerts.py alert --alert-id DS267 --custom-columns "property=value" --output-dir ./output
    python Get-LMAlerts.py alert --alert-id DS267 --debug --verbose

  Alternate credentials:
    python Get-LMAlerts.py --creds ./production.env account --hours-ago 24
    python Get-LMAlerts.py account --creds ./production.env --alert-id DS267

Notes:
  --days-ago means "alerts since N days ago"
  --hours-ago means "alerts since N hours ago" (account and device modes)
  --alert-id filters account/device results to one alert; alert mode fetches one alert directly
  --creds PATH loads ACCESS_ID, ACCESS_KEY, and COMPANY from PATH (default: .env)
  For device mode, explicit --start takes precedence over --days-ago
  Date is shown in Australia/Sydney
  Duration is computed from startEpoch/endEpoch, or startEpoch-to-now for active alerts
  Message is populated when detailMessage is returned by the API
  --save-table writes the displayed ASCII report to a .text file in the output directory
  --debug prints API URL, parameters, response status, and error details to stderr
  --verbose shows every field returned by the API
  Default alert output includes ruleId, chainId, receivedList, suppressor, suppressDesc,
  alertExternalTicketUrl, cleared, dependencyRoutingState, and dependencyRole
  externalTicketId (for ##EXTERNALTICKETID.<integrationName>##), dependencyMessage
  (##DEPENDENCYMESSAGE##), and dependentAlertCount (##DEPENDENTALERTCOUNT##)
  When --save-table is used, the saved table includes the full message body when available
  Saved table output does not append a separate Detail Message section
  JSON output is still saved under ./output by default
"""

    parser = argparse.ArgumentParser(
        prog="Get-LMAlerts.py",
        description="Fetch LogicMonitor alerts from the command line.",
        epilog=main_examples,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument("--creds", dest="creds", default=".env", help="Credentials .env file (default: .env)")
    subparsers = parser.add_subparsers(dest="command")

    account_examples = """Examples:
  python Get-LMAlerts.py account
  python Get-LMAlerts.py account --filter "cleared:false"
  python Get-LMAlerts.py account --days-ago 7
  python Get-LMAlerts.py account --save-table
"""

    account_parser = subparsers.add_parser(
        "account",
        help="Capture account-wide alerts",
        description="Capture account-wide alerts.",
        epilog=account_examples,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    account_parser.add_argument(
        "--filter",
        dest="lm_filter",
        help="Optional LogicMonitor filter string",
    )
    account_parser.add_argument(
        "--fields",
        help="Optional fields list",
    )
    account_parser.add_argument(
        "--days-ago",
        type=positive_int,
        help="Only show alerts from the last N days (examples: 1, 7, 14)",
    )
    account_parser.add_argument("--hours-ago", type=positive_int, help="Only show alerts from the last N hours")
    account_parser.add_argument("--alert-id", help="Only show the alert with this ID")
    account_parser.add_argument("--creds", dest="creds", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    account_parser.add_argument(
        "--page-size",
        type=int,
        default=DEFAULT_PAGE_SIZE,
        help=f"Page size for paginated requests (default: {DEFAULT_PAGE_SIZE})",
    )
    account_parser.add_argument(
        "--save-table",
        action="store_true",
        help="Save the displayed ASCII table/report to a .text file",
    )
    account_parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUT_DIR,
        help=f"Directory to save output files (default: {DEFAULT_OUT_DIR})",
    )
    account_parser.add_argument(
        "--debug", action="store_true", help="Print diagnostic API request details"
    )
    account_parser.add_argument(
        "--verbose", action="store_true", help="Show all fields returned by the API"
    )

    device_examples = """Examples:
  python Get-LMAlerts.py device --device-id 123
  python Get-LMAlerts.py device --device-id 123 --debug
  python Get-LMAlerts.py device --device-id 123 --need-message
  python Get-LMAlerts.py device --device-id 123 --days-ago 7
  python Get-LMAlerts.py device --device-id 123 --days-ago 14 --need-message --save-table
"""

    device_parser = subparsers.add_parser(
        "device",
        help="Capture alerts for a specific device",
        description="Capture alerts for a specific device.",
        epilog=device_examples,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    device_parser.add_argument(
        "--device-id",
        type=int,
        required=True,
        help="Device ID",
    )
    device_parser.add_argument(
        "--filter",
        dest="lm_filter",
        help="Optional LogicMonitor filter string",
    )
    device_parser.add_argument(
        "--fields",
        help="Optional fields list",
    )
    device_parser.add_argument(
        "--custom-columns",
        help="Optional customColumns value",
    )
    device_parser.add_argument(
        "--need-message",
        action="store_true",
        help="Include alert detail message where supported",
    )
    device_parser.add_argument(
        "--bound",
        default="instances",
        help='Bound value for device alerts (default: "instances")',
    )
    device_parser.add_argument(
        "--start",
        type=int,
        help="Optional start epoch (seconds or milliseconds)",
    )
    device_parser.add_argument(
        "--end",
        type=int,
        help="Optional end epoch (seconds or milliseconds)",
    )
    device_parser.add_argument(
        "--days-ago",
        type=positive_int,
        help="Only show alerts from the last N days (examples: 1, 7, 14)",
    )
    device_parser.add_argument("--hours-ago", type=positive_int, help="Only show alerts from the last N hours")
    device_parser.add_argument("--alert-id", help="Only show the alert with this ID")
    device_parser.add_argument("--creds", dest="creds", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    device_parser.add_argument(
        "--page-size",
        type=int,
        default=DEFAULT_PAGE_SIZE,
        help=f"Page size for paginated requests (default: {DEFAULT_PAGE_SIZE})",
    )
    device_parser.add_argument(
        "--save-table",
        action="store_true",
        help="Save the displayed ASCII table/report to a .text file",
    )
    device_parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUT_DIR,
        help=f"Directory to save output files (default: {DEFAULT_OUT_DIR})",
    )
    device_parser.add_argument(
        "--debug", action="store_true", help="Print diagnostic API request details"
    )
    device_parser.add_argument(
        "--verbose", action="store_true", help="Show all fields returned by the API"
    )

    alert_examples = """Examples:
  python Get-LMAlerts.py alert --alert-id DS267
  python Get-LMAlerts.py alert --alert-id DS267 --need-message
  python Get-LMAlerts.py alert --alert-id DS267 --need-message --save-table
"""

    alert_parser = subparsers.add_parser(
        "alert",
        help="Fetch a single alert by alert ID",
        description="Fetch a single alert by alert ID.",
        epilog=alert_examples,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    alert_parser.add_argument(
        "--alert-id",
        required=True,
        help="Alert ID",
    )
    alert_parser.add_argument("--creds", dest="creds", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    alert_parser.add_argument(
        "--need-message",
        action="store_true",
        help="Include alert detail message where supported",
    )
    alert_parser.add_argument(
        "--fields",
        help="Optional fields list",
    )
    alert_parser.add_argument(
        "--custom-columns",
        help="Optional customColumns value",
    )
    alert_parser.add_argument(
        "--save-table",
        action="store_true",
        help="Save the displayed ASCII table/report to a .text file",
    )
    alert_parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUT_DIR,
        help=f"Directory to save output files (default: {DEFAULT_OUT_DIR})",
    )
    alert_parser.add_argument(
        "--debug", action="store_true", help="Print diagnostic API request details"
    )
    alert_parser.add_argument(
        "--verbose", action="store_true", help="Show all fields returned by the API"
    )

    return parser


def main() -> int:
    global DEBUG
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 0

    load_credentials(args.creds)
    DEBUG = args.debug

    try:
        if args.command == "account":
            alerts = get_alerts_accountwide(
                lm_filter=args.lm_filter,
                fields=args.fields,
                page_size=args.page_size,
            )

            alerts = filter_alerts_since_hours(filter_alerts_since_days(alerts, args.days_ago), args.hours_ago)
            alerts = filter_alerts_by_id(alerts, args.alert_id)

            if alerts:
                title = (
                    f"Account Alerts (showing first {DEFAULT_PREVIEW_LIMIT} of "
                    f"{len(alerts)})"
                )
                if args.days_ago:
                    title += f" - last {args.days_ago} day(s)"
                console_report = build_alert_preview_report(
                    alerts,
                    title,
                    include_full_message_in_table=False,
                    verbose=args.verbose,
                )
                file_report = build_alert_preview_report(
                    alerts,
                    title,
                    include_full_message_in_table=True,
                    verbose=args.verbose,
                )
            else:
                if args.days_ago:
                    console_report = f"No alerts found in the last {args.days_ago} day(s)."
                else:
                    console_report = "No alerts found."
                file_report = console_report

            print_report(console_report)

            if args.save_table:
                text_filename = "getAlerts_accountwide.text"
                if args.days_ago:
                    text_filename = f"getAlerts_accountwide_{args.days_ago}d.text"
                save_text(args.output_dir, text_filename, file_report)

            json_filename = "getAlerts_accountwide.json"
            if args.days_ago:
                json_filename = f"getAlerts_accountwide_{args.days_ago}d.json"
            save_json(args.output_dir, json_filename, alerts)
            return 0

        if args.command == "device":
            effective_start = args.start
            if effective_start is None and args.days_ago is not None:
                effective_start = days_ago_to_epoch_seconds(args.days_ago)
            if effective_start is None and args.hours_ago is not None:
                effective_start = hours_ago_to_epoch_seconds(args.hours_ago)

            alerts = get_alerts_for_device(
                device_id=args.device_id,
                lm_filter=args.lm_filter,
                fields=args.fields,
                custom_columns=args.custom_columns,
                need_message=args.need_message,
                bound=args.bound,
                page_size=args.page_size,
                start=effective_start,
                end=args.end,
            )

            alerts = filter_alerts_since_hours(filter_alerts_since_days(alerts, args.days_ago), args.hours_ago)
            alerts = filter_alerts_by_id(alerts, args.alert_id)

            if alerts:
                title = (
                    f"Device Alerts for {args.device_id} "
                    f"(showing first {DEFAULT_PREVIEW_LIMIT} of {len(alerts)})"
                )
                if args.days_ago:
                    title += f" - last {args.days_ago} day(s)"
                console_report = build_alert_preview_report(
                    alerts,
                    title,
                    include_full_message_in_table=False,
                    verbose=args.verbose,
                )
                file_report = build_alert_preview_report(
                    alerts,
                    title,
                    include_full_message_in_table=True,
                    verbose=args.verbose,
                )
            else:
                if args.days_ago:
                    console_report = (
                        f"No alerts found for device ID {args.device_id} "
                        f"in the last {args.days_ago} day(s)."
                    )
                else:
                    console_report = f"No alerts found for device ID {args.device_id}."
                file_report = console_report

            print_report(console_report)

            if args.save_table:
                text_filename = f"getAlerts_device_{args.device_id}.text"
                if args.days_ago:
                    text_filename = (
                        f"getAlerts_device_{args.device_id}_{args.days_ago}d.text"
                    )
                save_text(args.output_dir, text_filename, file_report)

            json_filename = f"getAlerts_device_{args.device_id}.json"
            if args.days_ago:
                json_filename = (
                    f"getAlerts_device_{args.device_id}_{args.days_ago}d.json"
                )
            save_json(args.output_dir, json_filename, alerts)
            return 0

        if args.command == "alert":
            alert = get_alert_by_id(
                alert_id=args.alert_id,
                need_message=args.need_message,
                fields=args.fields,
                custom_columns=args.custom_columns,
            )

            console_report = build_single_alert_report(
                alert,
                include_full_message_in_table=False,
                include_detail_section=True,
                verbose=args.verbose,
            )
            file_report = build_single_alert_report(
                alert,
                include_full_message_in_table=True,
                include_detail_section=False,
                verbose=args.verbose,
            )

            print_report(console_report)

            if args.save_table:
                save_text(
                    args.output_dir,
                    f"getAlert_{sanitize_filename(args.alert_id)}.text",
                    file_report,
                )

            save_json(
                args.output_dir,
                f"getAlert_{sanitize_filename(args.alert_id)}.json",
                alert,
            )
            return 0

        parser.print_help()
        return 1

    except LMAPIError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        if DEBUG:
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
