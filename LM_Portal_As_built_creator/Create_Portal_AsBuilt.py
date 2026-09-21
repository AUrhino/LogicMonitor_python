#!/usr/bin/env python3
"""Create a read-only LogicMonitor portal as-built export.

The exporter intentionally keeps the API surface configurable and continues when
an endpoint is unavailable to the API user.  It writes raw JSON, flattened CSV
files, and a redacted Markdown document to a customer-named output directory.

Written by Ryan Gillan
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import hmac
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv


DEFAULT_TIMEOUT = 60
PAGE_SIZE = 1000
API_VERSION = "3"
__version__ = "1.04"
SECRET_WORDS = re.compile(r"(pass(word)?|secret|token|community|private.?key|api.?key|access.?key|bearer|auth)", re.I)


def cli() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export a LogicMonitor portal as-built document.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  Use .env in the current directory:
    python Create_Portal_AsBuilt.py --output ./customer-as-built

  Use a custom credentials file and show API diagnostics:
    python Create_Portal_AsBuilt.py --creds-file ./perpetual.env --output ./perpetual-as-built --debug

  Override only the portal name (credentials still come from .env):
    python Create_Portal_AsBuilt.py --company perpetual --output ./perpetual-as-built

  Export CSV and Markdown without raw JSON:
    python Create_Portal_AsBuilt.py --output ./customer-as-built --no-raw-json

  Write only /setting/companySetting to Markdown:
    python Create_Portal_AsBuilt.py --output ./customer-summary --summary

  Display the script version:
    python Create_Portal_AsBuilt.py --version
""",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument("--creds-file", "--env", default=".env", help="dotenv file; defaults to .env")
    parser.add_argument("--output", "-o", default="./as-built-output", help="Output folder")
    parser.add_argument("--company", help="Override COMPANY from dotenv")
    parser.add_argument("--access-id", help="Override ACCESS_ID from dotenv")
    parser.add_argument("--access-key", help="Override ACCESS_KEY from dotenv")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument(
        "--creator-file",
        default="creator.json",
        help="Document creator JSON file; defaults to creator.json",
    )
    parser.add_argument("--no-raw-json", action="store_true", help="Do not write raw JSON response files")
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Only collect /setting/companySetting and write it to Markdown",
    )
    parser.add_argument("--debug", action="store_true", help="Print API requests and non-fatal errors")
    if len(sys.argv) == 1:
        parser.print_help()
        raise SystemExit(0)
    return parser.parse_args()


def safe_name(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return value.strip("._") or "logicmonitor_portal"


def redact(value: Any, key: str = "") -> Any:
    if SECRET_WORDS.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(item, key) for item in value]
    return value


def scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(redact(value), ensure_ascii=False, default=str)
    return str(value)


def flatten(value: Any, prefix: str = "") -> dict[str, str]:
    """Flatten nested JSON into a useful one-row CSV representation."""
    result: dict[str, str] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            if SECRET_WORDS.search(str(key)):
                result[name] = "[REDACTED]"
            elif isinstance(child, (dict, list)):
                result.update(flatten(child, name))
            else:
                result[name] = scalar(child)
    elif isinstance(value, list):
        result[prefix] = scalar(value)
    else:
        result[prefix] = scalar(value)
    return result


class LogicMonitor:
    def __init__(self, company: str, access_id: str, access_key: str, timeout: int, debug: bool = False):
        self.company = company.strip()
        self.access_id = access_id
        self.access_key = access_key
        self.timeout = timeout
        self.debug = debug
        self.base = f"https://{self.company}.logicmonitor.com/santaba/rest"
        self.session = requests.Session()
        self.failures: list[dict[str, str]] = []
        self.skipped: list[dict[str, str]] = []

    def headers(self, method: str, resource: str, body: str = "") -> dict[str, str]:
        epoch = str(int(time.time() * 1000))
        message = method.upper() + epoch + body + resource
        digest = hmac.new(self.access_key.encode(), message.encode(), hashlib.sha256).hexdigest()
        signature = base64.b64encode(digest.encode()).decode()
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Version": API_VERSION,
            "Authorization": f"LMv1 {self.access_id}:{signature}:{epoch}",
        }

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        query = f"?{urlencode(params, doseq=True)}" if params else ""
        # LogicMonitor REST API v3 LMv1 signing uses the endpoint path only.
        # The /santaba/rest prefix and query string are not included in the
        # digest; they remain part of the actual request URL.
        signed_path = path
        url = self.base + path + query
        if self.debug:
            print(f"[DEBUG] GET {url}")
            print(f"[DEBUG] Signed resource: {signed_path}")
        try:
            response = self.session.get(
                self.base + path,
                params=params,
                headers=self.headers("GET", signed_path),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            if self.debug:
                print(f"[DEBUG] Request failed: {exc}")
            raise
        if self.debug:
            preview = re.sub(r"(?i)(access[_-]?key|token|password|secret)=([^&\s]+)", r"\1=[REDACTED]", response.text[:500])
            print(f"[DEBUG] Response: HTTP {response.status_code}, {len(response.content)} bytes")
            if response.status_code >= 400:
                print(f"[DEBUG] Response preview: {preview}")
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {"data": payload}

    def collection(
        self,
        name: str,
        path: str,
        params: dict[str, Any] | None = None,
        paginate: bool = True,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        offset = 0
        while True:
            query = (
                {"size": PAGE_SIZE, "offset": offset, **(params or {})}
                if paginate
                else dict(params or {})
            )
            try:
                payload = self.get(path, query)
            except requests.HTTPError as exc:
                response = exc.response
                response_text = response.text if response is not None else ""
                if (
                    response is not None
                    and response.status_code == 400
                    and "feature is not enabled for the company" in response_text.lower()
                ):
                    reason = "Feature is not enabled for this LogicMonitor portal"
                    self.skipped.append(
                        {"collection": name, "path": path, "reason": reason}
                    )
                    print(f"SKIPPED: {name}: {reason}")
                    return items
                message = str(exc)
                self.failures.append({"collection": name, "path": path, "error": message})
                if self.debug:
                    print(f"WARNING: {name}: {message}", file=sys.stderr)
                return items
            except (requests.RequestException, ValueError) as exc:
                message = str(exc)
                self.failures.append({"collection": name, "path": path, "error": message})
                if self.debug:
                    print(f"WARNING: {name}: {message}", file=sys.stderr)
                return items
            # API v3 normally returns {"items": [...]} directly. Some older
            # responses wrap that object in "data", so support both shapes.
            data = payload.get("data", payload)
            if isinstance(data, dict) and isinstance(data.get("items"), list):
                batch = data["items"]
            elif isinstance(data, dict):
                # Singleton/statistics/settings endpoints return one object
                # rather than a paginated items array.
                batch = [data]
            else:
                batch = data
            if not isinstance(batch, list):
                if self.debug:
                    print(f"[DEBUG] {name}: response did not contain data.items list; keys={list(payload)}")
                return items
            items.extend(item for item in batch if isinstance(item, dict))
            if self.debug:
                print(f"[DEBUG] {name}: received {len(batch)} rows; total={len(items)}")
            if not paginate or len(batch) < PAGE_SIZE:
                return items
            offset += PAGE_SIZE


COLLECTIONS: list[tuple[str, str, bool]] = [
    ("company_settings", "/setting/companySetting", False),
    ("alert_statistics", "/alert/stat", False),
    ("devices", "/device/devices", True),
    ("device_groups", "/device/groups", True),
    ("unmonitored_devices", "/device/unmonitoreddevices", True),
    ("collectors", "/setting/collector/collectors", True),
    ("collector_groups", "/setting/collector/groups", True),
    ("collector_versions", "/setting/collector/collectors/versions", True),
    ("collector_upgrade_history", "/setting/collector/collectors/upgradeHistory", False),
    ("alert_rules", "/setting/alert/rules", True),
    ("escalation_chains", "/setting/alert/chains", True),
    ("action_chains", "/setting/action/chains", False),
    ("action_rules", "/setting/action/rules", False),
    ("integrations", "/setting/integrations", True),
    ("users", "/setting/admins", True),
    ("api_tokens", "/setting/admins/apitokens", True),
    ("roles", "/setting/roles", True),
    ("access_groups", "/setting/accessgroup", True),
    ("dashboards", "/dashboard/dashboards", True),
    ("dashboard_groups", "/dashboard/groups", True),
    ("reports", "/report/reports", True),
    ("report_groups", "/report/groups", True),
    ("netscans", "/setting/netscans", True),
    ("websites", "/website/websites", True),
    ("website_groups", "/website/groups", True),
    ("website_checkpoints", "/website/smcheckpoints", True),
    ("logpipelines", "/logpipelines", False),
    ("logpipeline_processors", "/logpipelines/processors", False),
    ("log_sources", "/setting/logsources", False),
    ("log_partitions", "/log/partitions", False),
    ("log_retentions", "/log/partitions/retentions", False),
    ("log_query_groups", "/log/logquerygroups", False),
    ("datasource_modules", "/setting/datasources", True),
    ("configsource_modules", "/setting/configsources", True),
    ("eventsource_modules", "/setting/eventsources", True),
    ("propertysource_rules", "/setting/propertyrules", True),
    ("topology_sources", "/setting/topologysources", False),
    ("job_monitors", "/setting/batchjobs", False),
    ("applies_to_functions", "/setting/functions", True),
    ("oids", "/setting/oids", True),
    ("recipient_groups", "/setting/recipientgroups", True),
    ("sdts", "/sdt/sdts", True),
    ("ops_notes", "/setting/opsnotes", True),
    ("diagnostic_sources", "/setting/diagnosticsources", False),
    ("remediation_sources", "/setting/remediationsources", False),
    ("diagnostic_remediation_assignments", "/setting/diagnosticRemediation/list", False),
    ("metrics_usage", "/metrics/usage", False),
    ("metrics_summary", "/metrics/summary", False),
    ("contract_info", "/usage/contractInfo", False),
    ("focus_cost_usage", "/usage/focusCostUsage", True),
    ("cost_recommendations", "/cost-optimization/recommendations", True),
    ("cost_recommendation_categories", "/cost-optimization/recommendations/categories", True),
    ("aws_external_id", "/aws/externalId", False),
    ("aws_account_id", "/aws/accountId", False),
    ("external_api_stats", "/apiStats/externalApis", False),
    ("device_delta", "/device/devices/delta", False),
]



def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(redact(value), indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def clean_excluded_outputs(csv_dir: Path, json_dir: Path) -> None:
    """Remove stale generated files for datasets intentionally no longer collected."""
    excluded = {
        "audit_logs",
        "integration_audit_logs",
        "dashboard_widgets",
        "logicmodule_metadata",
        "tracked_query_groups",
        "diagnostic_remediation_results",
        "alerts",
        "api_get_coverage",
    }
    for directory, suffix in ((csv_dir, ".csv"), (json_dir, ".json")):
        for path in directory.glob(f"*_details{suffix}"):
            path.unlink(missing_ok=True)
        for name in excluded:
            (directory / f"{name}{suffix}").unlink(missing_ok=True)


def write_csv(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    flattened = [flatten(row) for row in rows]
    keys = sorted({key for row in flattened for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys or ["value"])
        writer.writeheader()
        for row in flattened:
            writer.writerow({key: row.get(key, "") for key in writer.fieldnames})
    return len(flattened)


def markdown_cell(value: Any, limit: int = 500) -> str:
    text = scalar(redact(value)).replace("|", "\\|").replace("\n", "<br>")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def load_creator(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to read creator file {path}: {exc}") from exc
    if isinstance(payload, list):
        payload = payload[0] if payload else {}
    if not isinstance(payload, dict):
        raise ValueError(f"Creator file {path} must contain an object or a list containing one object")
    return payload


def local_timestamp(creator: dict[str, Any]) -> str:
    requested = str(creator.get("date_format") or "dd-mm-yyyy")
    tokens = {
        "yyyy": "%Y", "yy": "%y", "dd": "%d", "mm": "%m",
        "HH": "%H", "MM": "%M", "ss": "%S",
    }
    pattern = requested
    for token in ("yyyy", "yy", "dd", "mm", "HH", "MM", "ss"):
        pattern = pattern.replace(token, tokens[token])
    return datetime.now().astimezone().strftime(pattern + " %H:%M:%S %Z")


def local_epoch_timestamp(value: Any, creator: dict[str, Any]) -> str:
    """Render an epoch value in local time using creator.json's date format."""
    try:
        epoch = float(value)
    except (TypeError, ValueError):
        return scalar(value)
    # Accommodate APIs that return epoch milliseconds instead of seconds.
    if epoch > 10_000_000_000:
        epoch /= 1000
    requested = str(creator.get("date_format") or "dd-mm-yyyy")
    tokens = {
        "yyyy": "%Y", "yy": "%y", "dd": "%d", "mm": "%m",
        "HH": "%H", "MM": "%M", "ss": "%S",
    }
    pattern = requested
    for token in ("yyyy", "yy", "dd", "mm", "HH", "MM", "ss"):
        pattern = pattern.replace(token, tokens[token])
    try:
        return datetime.fromtimestamp(epoch, tz=timezone.utc).astimezone().strftime(
            pattern + " %H:%M:%S %Z"
        )
    except (OverflowError, OSError, ValueError):
        return scalar(value)


def creator_header_lines(creator: dict[str, Any]) -> list[str]:
    if not creator:
        return []
    return [
        "",
        f"**Document creator:** {markdown_cell(creator.get('Creator', ''))}  ",
        f"**Email:** {markdown_cell(creator.get('Email', ''))}  ",
        f"**Title:** {markdown_cell(creator.get('Title', ''))}  ",
        f"**LogicMonitor address:** {markdown_cell(creator.get('LM_Addr', ''))}  ",
        f"**Document status:** {markdown_cell(creator.get('Document_Status', ''))}  ",
    ]


INSTANCE_COUNT_PREFIX = "numberOfInstancesPerDS."


def company_settings_table(row: dict[str, Any]) -> dict[str, str]:
    return {
        key: value
        for key, value in flatten(row).items()
        if not key.lower().startswith(INSTANCE_COUNT_PREFIX.lower())
    }


def write_instance_count_files(output: Path, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    instance_dir = output / "numberOfInstancesPerDS"
    instance_dir.mkdir(exist_ok=True)
    instance_counts = {
        key: value
        for key, value in flatten(rows[0]).items()
        if key.lower().startswith(INSTANCE_COUNT_PREFIX.lower())
    }
    for key, value in instance_counts.items():
        filename = safe_name(key) + ".md"
        lines = [
            f"# {key}",
            "",
            "Extracted from `/setting/companySetting` to keep the main as-built document compact.",
            "",
            "| Setting | Value |",
            "|---|---|",
            f"| `{key}` | {markdown_cell(value, 10000)} |",
            "",
        ]
        (instance_dir / filename).write_text("\n".join(lines), encoding="utf-8")
    return len(instance_counts)


def prepare_markdown_folder(root: Path) -> Path:
    """Create the auxiliary Markdown folder and relocate known legacy outputs."""
    markdown_dir = root / "markdown"
    markdown_dir.mkdir(exist_ok=True)
    instance_dir = markdown_dir / "numberOfInstancesPerDS"
    instance_dir.mkdir(exist_ok=True)
    folder_structure = root / "folder_structure.md"
    if folder_structure.is_file():
        folder_structure.replace(markdown_dir / folder_structure.name)
    legacy_files = [
        *root.glob("numberOfInstancesPerDS.*.md"),
        *markdown_dir.glob("numberOfInstancesPerDS.*.md"),
    ]
    for source in legacy_files:
        if source.is_file():
            source.replace(instance_dir / source.name)
    return markdown_dir


MODULE_TABLE_FIELDS = (
    "name", "displayName", "isInUse", "id", "description"
)

DATASET_TABLE_FIELDS: dict[str, tuple[str, ...]] = {
    "devices": (
        "name", "displayName", "description", "currentCollectorId", "hostStatus",
        "deviceType", "createdOn", "updatedOn", "disableAlerting",
    ),
    "services": ("id", "name", "displayName", "description", "deviceType", "hostStatus"),
    "unmonitored_devices": ("id", "ip", "dns", "sysname", "displayAs", "deviceType"),
    "datasources": (
        "id", "dataSourceId", "dataSourceName", "dataSourceDisplayName",
    ),
    "collectors": (
        "id", "hostname", "description", "collectorSize", "arch", "build",
        "numberOfInstances", "userVisibleHostsNum", "collectorGroupId", "collectorGroupName",
    ),
    "collector_versions": (
        "majorVersion", "minorVersion", "mandatory", "stable", "releaseEpoch",
        "has32bitWindows", "has32bitLinux",
    ),
    "alert_rules": (
        "id", "name", "priority", "levelStr", "escalatingChainId", "escalationInterval",
    ),
    "escalation_chains": (
        "id", "name", "description", "enableThrottling", "throttlingPeriod",
        "throttlingAlerts", "inAlerting", "destinations", "ccDestinations",
    ),
    "action_chains": ("id", "name", "description", "stages"),
    "action_rules": ("id", "name", "enabled"),
    "integrations": ("id", "name", "description", "type", "enabledStatus"),
    "api_tokens": (
        "id", "accessId", "accessKey", "roles", "status", "adminName", "note",
    ),
    "roles": ("id", "name", "description", "associatedUserCount"),
    "access_groups": ("id", "name"),
    "dashboards": ("id", "fullName", "description"),
    "reports": ("id", "name", "type", "format", "description"),
    "website_checkpoints": (
        "id", "name", "geoInfo", "description", "displayPrio", "isEnabledInRoot",
    ),
    "oids": ("id", "oid", "categories"),
}

DATASET_EXCLUDED_FIELDS: dict[str, set[str]] = {
    "datasources": {"assignedOn", "createdOn", "updatedOn", "status"},
    "netscans": {
        "version", "collectorDescription", "collectordescription", "collectorGroup",
        "collectorgroup", "creator", "exchangeVendorPath",
    },
}

MODULE_DATASETS = {
    "datasource_modules",
    "configsource_modules",
    "eventsource_modules",
    "propertysource_rules",
    "topology_sources",
    "log_sources",
    "job_monitors",
    "applies_to_functions",
    "oids",
    "diagnostic_sources",
    "remediation_sources",
}


def dataset_table(
    name: str,
    rows: list[dict[str, Any]],
    creator: dict[str, Any] | None = None,
) -> list[str]:
    fields = DATASET_TABLE_FIELDS.get(name)
    if fields is None and name in MODULE_DATASETS:
        fields = MODULE_TABLE_FIELDS
    if fields is None:
        preferred = (
            "id", "name", "displayName", "fullName", "description", "type",
            "status", "enabled", "version", "groupId", "createdOn", "updatedOn",
        )
        available = {key for row in rows for key, value in row.items() if not isinstance(value, (dict, list))}
        selected = [key for key in preferred if key in available]
        selected.extend(key for key in sorted(available) if key not in selected)
        fields = tuple(selected[:12])
    excluded = DATASET_EXCLUDED_FIELDS.get(name, set())
    fields = tuple(field for field in fields if field not in excluded)
    if not fields:
        return ["No tabular fields were returned.", ""]
    lines = [
        "| " + " | ".join(fields) + " |",
        "| " + " | ".join("---" for _ in fields) + " |",
    ]
    for row in rows:
        values = []
        for field in fields:
            value = "[REDACTED]" if SECRET_WORDS.search(field) else row.get(field, "")
            if name == "devices" and field in {"createdOn", "updatedOn"}:
                value = local_epoch_timestamp(value, creator or {})
            values.append(markdown_cell(value, 300))
        lines.append("| " + " | ".join(values) + " |")
    lines.append("")
    return lines


def portal_monitoring_section(
    company: str, devices: list[dict[str, Any]]
) -> list[str]:
    """Describe the LogicMonitor portal resource when it exists in Devices."""
    portal_name = f"{company}.logicmonitor.com"
    matches = [
        device
        for device in devices
        if any(
            str(device.get(field, "")).strip().lower() == portal_name.lower()
            for field in ("name", "displayName")
        )
    ]
    lines = [
        "### Portal Monitoring",
        "",
        f"Portal resource searched: `{portal_name}`  ",
        "Guidance: [LogicMonitor portal monitoring](https://www.logicmonitor.com/support/logicmonitor-portal-monitoring)",
        "",
    ]
    if not matches:
        return lines + ["No matching portal monitoring resource was found.", ""]
    lines += [
        "| id | name | displayName |",
        "|---|---|---|",
    ]
    for device in matches:
        lines.append(
            "| "
            + " | ".join(
                markdown_cell(device.get(field, ""), 300)
                for field in ("id", "name", "displayName")
            )
            + " |"
        )
    lines.append("")
    return lines


def group_tree_lines(groups: list[dict[str, Any]]) -> list[str]:
    """Build an ASCII hierarchy from LogicMonitor group records."""
    if not groups:
        return ["└── (none returned)"]

    def value(row: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if row.get(key) not in (None, ""):
                return row[key]
        return None

    nodes: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(groups, 1):
        node_id = value(row, "id", "groupId", "collectorGroupId")
        nodes[str(node_id if node_id is not None else f"row-{index}")] = row

    children: dict[str | None, list[str]] = {}
    for node_id, row in nodes.items():
        parent = value(row, "parentId", "parentID", "parent_id", "parentGroupId")
        parent_key = str(parent) if parent is not None else None
        if parent_key in {"0", "-1", node_id} or parent_key not in nodes:
            parent_key = None
        children.setdefault(parent_key, []).append(node_id)

    def label(node_id: str) -> str:
        row = nodes[node_id]
        name = value(row, "name", "displayName", "description", "fullPath")
        return str(name if name is not None else f"Group {node_id}")

    for node_ids in children.values():
        node_ids.sort(key=lambda item: label(item).lower())

    lines: list[str] = []

    def walk(node_id: str, prefix: str, is_last: bool, ancestors: set[str]) -> None:
        connector = "└── " if is_last else "├── "
        lines.append(prefix + connector + label(node_id))
        if node_id in ancestors:
            lines.append(prefix + ("    " if is_last else "│   ") + "└── [cycle detected]")
            return
        child_ids = children.get(node_id, [])
        child_prefix = prefix + ("    " if is_last else "│   ")
        for index, child_id in enumerate(child_ids):
            walk(child_id, child_prefix, index == len(child_ids) - 1, ancestors | {node_id})

    roots = children.get(None, [])
    for index, node_id in enumerate(roots):
        walk(node_id, "", index == len(roots) - 1, set())
    return lines or ["└── (none returned)"]


def write_folder_structure(
    path: Path,
    company: str,
    datasets: dict[str, list[dict[str, Any]]],
) -> None:
    sections = (
        ("Resource groups", "device_groups"),
        ("Website groups", "website_groups"),
        ("Dashboard groups", "dashboard_groups"),
        ("Report groups", "report_groups"),
        ("Collector groups", "collector_groups"),
    )
    lines = [
        f"# {company} LogicMonitor folder structure",
        "",
        "Generated from the LogicMonitor REST API. Each hierarchy starts at its returned root group.",
        "",
    ]
    for title, dataset_name in sections:
        lines += [f"## {title}", "", "```text", "Root"]
        tree = group_tree_lines(datasets.get(dataset_name, []))
        lines.extend("    " + line for line in tree)
        lines += ["```", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_summary_markdown(
    path: Path,
    company: str,
    generated: str,
    rows: list[dict[str, Any]],
    failures: list[dict[str, str]],
    creator: dict[str, Any],
) -> None:
    display = company.replace("_", " ").replace("-", " ").title()
    lines = [
        f"# {display} — LogicMonitor Company Settings",
        "",
        f"**Portal:** `{company}.logicmonitor.com`  ",
        f"**Generated:** {generated} / **Local time:** {local_timestamp(creator)}  ",
        f"**Exporter version:** {__version__}  ",
        "**Endpoint:** `/setting/companySetting`  ",
        "**Credential handling:** secret-like values are redacted.  ",
    ]
    lines += creator_header_lines(creator)
    lines += [
        "",
        "## Company settings",
        "",
    ]
    if rows:
        settings = company_settings_table(rows[0])
        lines += ["| Setting | Value |", "|---|---|"]
        for key in sorted(settings):
            lines.append(f"| `{key}` | {markdown_cell(settings[key])} |")
        instance_count_total = len(flatten(rows[0])) - len(settings)
        if instance_count_total:
            lines += [
                "",
                f"{instance_count_total} `numberOfInstancesPerDS.*` setting(s) were moved to separate files under `markdown/numberOfInstancesPerDS/`.",
            ]
    else:
        lines.append("No company settings were returned.")
    if failures:
        lines += ["", "## Collection failure", "", "| Path | Error |", "|---|---|"]
        for failure in failures:
            lines.append(
                f"| `{failure['path']}` | {markdown_cell(failure['error'])} |"
            )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_markdown(
    path: Path,
    company: str,
    generated: str,
    counts: dict[str, int],
    failures: list[dict[str, str]],
    skipped: list[dict[str, str]],
    datasets: dict[str, list[dict[str, Any]]],
    creator: dict[str, Any],
    output: Path,
) -> None:
    display = company.replace("_", " ").replace("-", " ").title()
    lines = [
        f"# {display} — LogicMonitor As-Built",
        "",
        f"**Portal:** `{company}.logicmonitor.com`  ",
        f"**Generated:** {generated} / **Local time:** {local_timestamp(creator)}  ",
        "**Source:** LogicMonitor REST API (read-only export)  ",
        "**Credential handling:** credential values and secret-like properties are redacted.  ",
    ]
    lines += creator_header_lines(creator)
    lines += [
        "",
        "> This document is generated from the portal state available to the API user. Review the evidence CSV/JSON files and complete the operational notes before customer handover.",
        "",
        "## Document control",
        "",
        "| Item | Value |",
        "|---|---|",
        f"| Customer / portal | {display} / `{company}` |",
        "| Project / implementation dates | Complete during handover |",
        "| Document owner / reviewers | Complete during handover |",
        f"| Version | 1.0 — generated {generated} |",
        "| Assumptions / exclusions | See `collection_failures.csv`; undocumented implementation decisions require review |",
        "",
        "## Implementation summary",
        "",
        "This export inventories portal configuration, collectors, resources, monitoring modules, alerting, integrations, cloud/web resources, dashboards, reports, and RBAC objects where the API user has access. It is an evidence pack, not a change record; add design rationale, deviations, limitations, and deferred items during review.",
        "",
        "## Portal and account configuration",
        "",
        f"- Portal URL: `https://{company}.logicmonitor.com`",
        "- Time zone, naming conventions, group purpose, global settings, and implementation decisions: complete during handover.",
        "- Raw portal settings and API responses are in `json/company_settings.json` and the related CSV file.",
        "",
        "### Company settings",
        "",
    ]
    company_rows = datasets.get("company_settings", [])
    if company_rows:
        settings = company_settings_table(company_rows[0])
        lines += ["| Setting | Value |", "|---|---|"]
        for key in sorted(settings):
            lines.append(f"| `{key}` | {markdown_cell(settings[key])} |")
        instance_count_total = len(flatten(company_rows[0])) - len(settings)
        if instance_count_total:
            lines += [
                "",
                f"{instance_count_total} `numberOfInstancesPerDS.*` setting(s) were moved to separate files under `markdown/numberOfInstancesPerDS/`.",
            ]
    else:
        lines.append("Company settings were not returned; see collection failures or skipped features.")
    lines += ["", "### Alert statistics and versions", ""]
    alert_rows = datasets.get("alert_statistics", [])
    if alert_rows:
        stats = flatten(alert_rows[0])
        lines += ["| Field | Value |", "|---|---|"]
        for key in sorted(stats):
            lines.append(f"| `{key}` | {markdown_cell(stats[key])} |")
    else:
        lines.append("Alert statistics were not returned; see collection failures or skipped features.")
    lines += ["", "## Exported evidence", "", "| Dataset | Rows | Evidence |", "|---|---:|---|"]
    for name, count in counts.items():
        evidence = f"`csv/{name}.csv` and `json/{name}.json`"
        if name == "device_groups":
            evidence += " and `markdown/folder_structure.md`"
        lines.append(f"| {name.replace('_', ' ').title()} | {count} | {evidence} |")
    markdown_files = sorted((output / "markdown").glob("*.md"))
    for markdown_file in markdown_files:
        lines.append(
            f"| {markdown_file.stem.replace('_', ' ').title()} | — | `markdown/{markdown_file.name}` |"
        )
    instance_count_dir = output / "markdown" / "numberOfInstancesPerDS"
    if any(instance_count_dir.glob("*.md")):
        lines.append(
            "| Number Of Instances Per DataSource | — | `markdown/numberOfInstancesPerDS/` |"
        )
    lines += ["", "## Collected API datasets", ""]
    for name, rows in datasets.items():
        if name == "datasources":
            continue
        title = name.replace("_", " ").title()
        lines += [f"### {title}", "", f"**Rows:** {len(rows)}  ", f"**Evidence:** `csv/{name}.csv` and `json/{name}.json`", ""]
        if name in {"company_settings", "alert_statistics"}:
            lines += ["A complete formatted table appears above.", ""]
            continue
        if name == "device_groups":
            lines += [
                "The LogicMonitor Resource Group hierarchy is documented in `markdown/folder_structure.md`.",
                "",
            ]
            continue
        if not rows:
            lines += ["No items were returned.", ""]
            if name == "devices":
                lines += portal_monitoring_section(company, rows)
            continue
        lines += dataset_table(name, rows, creator)
        if name == "devices":
            lines += portal_monitoring_section(company, rows)
    lines += [
        "",
        "## Collector design and deployment",
        "",
        "Review `collectors.csv` and `collector_groups.csv` for IDs, versions, groups, status, platform, and assignment fields. Record network zones, proxy/firewall requirements, upgrade policy, failover strategy, and local configuration changes during handover.",
        "",
        "## Resource inventory, protocols, and credentials",
        "",
        "Review `devices.csv`, `device_groups.csv`, `datasources.csv`, `netscans.csv`, and `websites.csv`. Property names are retained where returned, but secret-like values are redacted. Record protocol, inherited credential property names, least-privilege requirements, ports, and validation method without adding secrets.",
        "",
        "## LogicModules and alerting",
        "",
        "Review DataSources and alert datasets for deployed modules, versions, AppliesTo expressions, thresholds, discovery, disabled modules, alert priority, routing, escalation intervals, SDT, dependencies, and historical-data considerations.",
        "",
        "## Integrations, cloud, Kubernetes, logs, dashboards, and RBAC",
        "",
        "The API export records objects exposed by the selected endpoints. Add implementation-specific cloud permissions, Kubernetes/LM Logs configuration, dashboard/report schedules, topology maps, SSO/2FA, API-only users, and access-group decisions that are not represented in the returned objects.",
        "",
        "## Validation and operational handover",
        "",
        "| Area | Validation performed | Result | Evidence / notes |",
        "|---|---|---|---|",
        "| Collector | Online and polling | Complete during handover | Collector ID / screenshot |",
        "| WMI / SNMP / API | Test collection | Complete during handover | Redacted output |",
        "| Alerts | Test alert routed | Complete during handover | Alert ID |",
        "| Integrations | Create/update/close behavior | Complete during handover | External ID |",
        "| Dashboards / reports | Populated and scheduled | Complete during handover | Screenshot / recipient |",
        "| Logs | Events searchable | Complete during handover | Query / timestamp |",
        "",
        "Add support contacts, runbooks, collector log locations, troubleshooting paths, resource onboarding steps, module update process, SDT procedure, known issues, and open actions.",
        "",
        "## Collection failures and limitations",
        "",
    ]
    if failures:
        lines.append("The following endpoints could not be collected with the supplied API identity. Treat these as review items, not as evidence that the configuration is absent.")
        lines += ["", "| Dataset | Path | Error |", "|---|---|---|"]
        for failure in failures:
            lines.append(f"| {failure['collection']} | `{failure['path']}` | {failure['error'].replace('|', '\\|')} |")
    else:
        lines.append("No endpoint failures were reported.")
    lines += ["", "## Unavailable portal features", ""]
    if skipped:
        lines += ["| Dataset | Path | Reason |", "|---|---|---|"]
        for item in skipped:
            lines.append(
                f"| {item['collection']} | `{item['path']}` | {item['reason']} |"
            )
    else:
        lines.append("No collections were skipped because of disabled portal features.")
    lines += [
        "",
        "## Notes",
        "",
        "#### Notes:",
        "",
        "- Never commit the raw output directory if it contains customer-sensitive configuration.",
        "",
        "- Contact LogicMonitor PS support to run this code/provide the source.",
        "",
        "## File details",
        "",
        "```text",
        ".",
        "├── csv",
        "├── json",
        "├── markdown",
        "│   ├── folder_structure.md",
        "│   └── numberOfInstancesPerDS",
        f"└── {path.name}",
        "```",
        "",
        "End of document.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = cli()
    load_dotenv(args.creds_file, override=True)
    company = args.company or os.getenv("COMPANY") or os.getenv("LM_COMPANY")
    access_id = args.access_id or os.getenv("ACCESS_ID") or os.getenv("LM_ACCESS_ID")
    access_key = args.access_key or os.getenv("ACCESS_KEY") or os.getenv("LM_ACCESS_KEY")
    if not company or not access_id or not access_key:
        print("Missing credentials. Set COMPANY, ACCESS_ID, and ACCESS_KEY or use the override arguments.", file=sys.stderr)
        return 2

    creator_path = Path(args.creator_file).expanduser()
    if not creator_path.exists() and args.creator_file == "creator.json":
        creator_path = Path(__file__).with_name("creator.json")
    try:
        creator = load_creator(creator_path)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.debug:
        print("[DEBUG] ============ LogicMonitor export configuration ============")
        print(f"[DEBUG] Portal: https://{company}.logicmonitor.com")
        print(f"[DEBUG] Credentials file: {Path(args.creds_file).expanduser().resolve()}")
        print(f"[DEBUG] API version: {API_VERSION}")
        print("[DEBUG] Access ID/key: loaded (values not displayed)")
        print("[DEBUG] ===========================================================")

    root = Path(args.output).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    markdown_dir = prepare_markdown_folder(root)
    client = LogicMonitor(company, access_id, access_key, args.timeout, args.debug)
    counts: dict[str, int] = {}
    datasets: dict[str, list[dict[str, Any]]] = {}
    started = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    if args.summary:
        print("Collecting company_settings...")
        rows = client.collection(
            "company_settings", "/setting/companySetting", paginate=False
        )
        write_instance_count_files(markdown_dir, rows)
        markdown_path = root / f"{safe_name(company)}_As_Built.md"
        write_summary_markdown(
            markdown_path, company, started, rows, client.failures, creator
        )
        print(f"\nCreated company-settings summary: {markdown_path}")
        return 0 if rows else 1

    csv_dir, json_dir = root / "csv", root / "json"
    csv_dir.mkdir(exist_ok=True)
    json_dir.mkdir(exist_ok=True)
    clean_excluded_outputs(csv_dir, json_dir)

    for name, endpoint, paginate in COLLECTIONS:
        print(f"Collecting {name}...")
        collection_params = {"sort": "+id"} if name in {"dashboards", "oids"} else None
        rows = client.collection(
            name, endpoint, params=collection_params, paginate=paginate
        )
        datasets[name] = rows
        counts[name] = write_csv(csv_dir / f"{name}.csv", rows)
        if not args.no_raw_json:
            write_json(json_dir / f"{name}.json", rows)

        # DataSources are a device sub-resource in REST API v3. They cannot be
        # collected from a guessed global /device/devices/devicedatasources URL.
        if name == "devices":
            print("Collecting services...")
            service_rows = client.collection(
                "services",
                "/device/devices",
                params={"filter": 'deviceType:"6"', "sort": "+id"},
            )
            datasets["services"] = service_rows
            counts["services"] = write_csv(csv_dir / "services.csv", service_rows)
            if not args.no_raw_json:
                write_json(json_dir / "services.json", service_rows)

            datasource_rows: list[dict[str, Any]] = []
            for device in rows:
                device_id = device.get("id")
                if device_id is None:
                    continue
                datasource_rows.extend(
                    {
                        "deviceId": device_id,
                        **datasource,
                    }
                    for datasource in client.collection(
                        f"datasources_{device_id}",
                        f"/device/devices/{device_id}/devicedatasources",
                    )
                )
            counts["datasources"] = write_csv(csv_dir / "datasources.csv", datasource_rows)
            datasets["datasources"] = datasource_rows
            if not args.no_raw_json:
                write_json(json_dir / "datasources.json", datasource_rows)

    write_instance_count_files(markdown_dir, datasets.get("company_settings", []))
    write_folder_structure(markdown_dir / "folder_structure.md", company, datasets)
    write_csv(csv_dir / "collection_failures.csv", client.failures)
    write_csv(csv_dir / "collection_skipped.csv", client.skipped)
    write_markdown(
        root / f"{safe_name(company)}_As_Built.md",
        company,
        started,
        counts,
        client.failures,
        client.skipped,
        datasets,
        creator,
        root,
    )
    print(f"\nCreated as-built export in: {root}")
    print(f"Markdown_report: {safe_name(company)}_As_Built.md")
    print("Folder_Structure: markdown/folder_structure.md")
    print(
        f"Datasets: {len(counts)}; endpoint failures: {len(client.failures)}; "
        f"unavailable features: {len(client.skipped)}"
    )
    if client.failures:
        print("Failed collections:")
        for failure in client.failures:
            collection = failure.get("collection", "unknown")
            endpoint = failure.get("path", "unknown endpoint")
            error = str(failure.get("error", "Unknown error")).replace("\n", " ")
            print(f"- {collection}: {endpoint} — {error}")
    else:
        print("Failed collections: none")
    if client.skipped:
        print("Unavailable portal features:")
        for item in client.skipped:
            collection = item.get("collection", "unknown")
            endpoint = item.get("path", "unknown endpoint")
            reason = str(item.get("reason", "Unavailable")).replace("\n", " ")
            print(f"- {collection}: {endpoint} — {reason}")
    # Post-run handover review instructions.
    document_status = creator.get("Document_Status") or "DRAFT"
    print("Review:")
    print(f"This document has been marked as: {document_status}")
    print(
        "Review and PDF the Markdown preview version. Provide the customer a ZIP "
        "of this folder."
    )
    print("Suggested files to review:")
    print(f"- {safe_name(company)}_As_Built.md — main report and Markdown preview")
    print("- markdown/folder_structure.md — LogicMonitor group hierarchy")
    print("- csv/collection_failures.csv — failed API collections")
    print("- csv/collection_skipped.csv — unavailable portal features")
    print("- csv/devices.csv — resource inventory")
    print("- csv/collectors.csv — collector inventory")
    print("- csv/integrations.csv — integration inventory")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
