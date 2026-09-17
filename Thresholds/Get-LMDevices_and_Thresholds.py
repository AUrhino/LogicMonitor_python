#!/usr/bin/env python3
"""Export LogicMonitor alert-threshold overrides for devices in a group."""

import argparse
import base64
import csv
import hashlib
import hmac
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv


load_dotenv()
ACCESS_KEY = os.getenv("ACCESS_KEY")
ACCESS_ID = os.getenv("ACCESS_ID")
COMPANY = os.getenv("COMPANY")
BASE_URL = f"https://{COMPANY}.logicmonitor.com/santaba/rest"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Export LogicMonitor alert-threshold overrides for a device group.",
        epilog=(
            "Examples:\n"
            "  python3 Get-LMDevices_and_Thresholds.py --groupid 123\n"
            "  python3 Get-LMDevices_and_Thresholds.py --groupid 123 --output output/thresholds.csv\n"
            "  python3 Get-LMDevices_and_Thresholds.py --groupid 123 --creds-file ~/.logicmonitor.env --debug"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--groupid", required=True, help="LogicMonitor device group ID.")
    parser.add_argument("--subGroups", type=str_to_bool, default=False, metavar="true|false",
                        help="Include child groups recursively (default: false).")
    parser.add_argument(
        "--creds-file", metavar="PATH",
        help="Load ACCESS_ID, ACCESS_KEY, and COMPANY from a dotenv credentials file.",
    )
    parser.add_argument("--resource", metavar="DISPLAY_NAME", help="Only process this resource display name.")
    parser.add_argument("--instance", metavar="NAME", help="Only process this DataSource instance name.")
    parser.add_argument("--datapoint", metavar="NAME", help="Only export this datapoint name.")
    parser.add_argument("--alertStatus", action="store_true",
                        help="Include alertDisableStatus and its meaning in the CSV output.")
    parser.add_argument(
        "--output", "--csv", dest="output_path", default="output.csv",
        help="CSV output path (default: output.csv).",
    )
    parser.add_argument("--debug", action="store_true", help="Print API URLs and response status.")
    if len(sys.argv) == 1:
        parser.print_help()
        raise SystemExit(0)
    return parser.parse_args()


def api_get(path, params=None, debug=False):
    epoch = str(int(time.time() * 1000))
    digest = hmac.new(
        ACCESS_KEY.encode(), ("GET" + epoch + path).encode(), hashlib.sha256
    ).hexdigest()
    signature = base64.b64encode(digest.encode()).decode()
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Version": "3",
        "Authorization": f"LMv1 {ACCESS_ID}:{signature}:{epoch}",
    }
    query = urlencode(params or {})
    url = BASE_URL + path + (("?" + query) if query else "")
    if debug:
        print(f"[DEBUG] GET {url}")
    response = requests.get(url, headers=headers, timeout=60)
    if debug:
        print(f"[DEBUG] HTTP {response.status_code}")
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def get_items(path, params=None, debug=False):
    payload = api_get(path, params, debug)
    data = payload.get("data", payload)
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    return data if isinstance(data, list) else []


def str_to_bool(value):
    if value.strip().lower() in ("true", "t", "yes", "y", "1"):
        return True
    if value.strip().lower() in ("false", "f", "no", "n", "0"):
        return False
    raise argparse.ArgumentTypeError("Expected true or false.")


def get_group(group_id, debug=False):
    try:
        return api_get(f"/device/groups/{group_id}", {"size": 1000, "offset": 0}, debug)
    except requests.RequestException as error:
        print(f"Warning: request failed for group {group_id}: {error}")
        return {}


def collect_groups(group_id, include_subgroups, debug=False):
    groups = []

    def visit(current_id):
        group = get_group(current_id, debug)
        if not group:
            return
        groups.append((current_id, group))
        if include_subgroups:
            for child in group.get("subGroups", []) or []:
                if isinstance(child, dict) and child.get("id") is not None:
                    visit(child["id"])

    visit(group_id)
    return groups


def alert_items(path, debug):
    try:
        payload = api_get(path, {"size": 1000, "offset": 0}, debug)
        data = payload.get("data", payload)
        if isinstance(data, dict):
            if isinstance(data.get("items"), list):
                return data["items"]
            # Group-level alert settings use dpConfig rather than items.
            if isinstance(data.get("dpConfig"), list):
                return data["dpConfig"]
        return data if isinstance(data, list) else []
    except requests.RequestException as error:
        print(f"Warning: request failed for {path}: {error}")
        return []


def alert_status_meaning(value):
    meanings = {
        "none-disable-none": "Alerting is disabled directly on the device.",
        "disable-none-none": "Alerting is disabled by a device group the device belongs to.",
        "none-none-disable": "Alerting is disabled below the device, such as on a DataSource, instance, or datapoint.",
        "none-none-none": "No alert-disable condition exists at the group, device, or child/sub-resource levels.",
    }
    return meanings.get(value, "Unknown or mixed alert-disable status.")


def threshold_rows(items, resource, module, threshold_level, datapoint_filter=None,
                  alert_status=None):
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if datapoint_filter and str(item.get("dataPointName", "")).casefold() != datapoint_filter.casefold():
            continue
        expression = item.get("alertExpr")
        default_expression = item.get("globalAlertExpr")
        # Only export an override. Empty expressions mean that no threshold is set.
        if expression in (None, "") or expression == default_expression:
            continue
        row = [
            item.get("dataPointId"),
            resource,
            module,
            threshold_level,
            expression,
        ]
        if alert_status is not None:
            row.extend([alert_status, alert_status_meaning(alert_status)])
        rows.append(row)
    return rows


def main():
    global ACCESS_KEY, ACCESS_ID, COMPANY, BASE_URL
    args = parse_args()
    if args.creds_file:
        credentials_path = Path(args.creds_file).expanduser()
        if not credentials_path.is_file():
            raise SystemExit(f"Credentials file not found: {credentials_path}")
        load_dotenv(credentials_path, override=True)
        ACCESS_KEY = os.getenv("ACCESS_KEY")
        ACCESS_ID = os.getenv("ACCESS_ID")
        COMPANY = os.getenv("COMPANY")
        BASE_URL = f"https://{COMPANY}.logicmonitor.com/santaba/rest"
    missing = [
        name for name, value in
        (("ACCESS_ID", ACCESS_ID), ("ACCESS_KEY", ACCESS_KEY), ("COMPANY", COMPANY))
        if not value
    ]
    if missing:
        raise SystemExit(f"Missing required environment variable(s): {', '.join(missing)}")

    groups = collect_groups(args.groupid, args.subGroups, args.debug)
    device_groups = []
    for group_id, group in groups:
        print(f"Working on Group id {group_id}")
        print(f"Name: {group.get('name', '')}")
        print(f"Description: {group.get('description', '')}")
        try:
            group_devices = get_items(
                f"/device/groups/{group_id}/devices",
                {"size": 1000, "offset": 0},
                args.debug,
            )
        except requests.RequestException as error:
            print(f"Warning: unable to fetch devices for group {group_id}: {error}")
            group_devices = []
        print(f"Device count: {len(group_devices)}")
        device_groups.extend((device, group_id) for device in group_devices)

    rows = []
    for device, current_group_id in device_groups:
        if not isinstance(device, dict) or device.get("id") is None:
            continue
        device_id = device["id"]
        resource = device.get("displayName") or device.get("name") or device_id
        if args.resource and str(device.get("displayName", "")).casefold() != args.resource.casefold():
            continue
        datasources = get_items(
            f"/device/devices/{device_id}/devicedatasources",
            {"size": 1000, "offset": 0},
            args.debug,
        )
        for datasource in datasources:
            if not isinstance(datasource, dict):
                continue
            datasource_id = datasource.get("id", datasource.get("dataSourceId"))
            module_datasource_id = datasource.get("dataSourceId", datasource_id)
            module = datasource.get("dataSourceName") or datasource.get("dataSourceDisplayName") or datasource_id
            if datasource_id is None:
                continue
            instances = get_items(
                f"/device/devices/{device_id}/devicedatasources/{datasource_id}/instances",
                {"size": 1000, "offset": 0},
                args.debug,
            )
            matching_instance = not args.instance
            for instance in instances:
                if not isinstance(instance, dict):
                    continue
                instance_id = instance.get("id", instance.get("instanceId"))
                if instance_id is None:
                    continue
                if args.instance and str(instance.get("name", "")).casefold() != args.instance.casefold():
                    continue
                matching_instance = True
                rows.extend(threshold_rows(
                    alert_items(
                        f"/device/devices/{device_id}/devicedatasources/{datasource_id}/instances/{instance_id}/alertsettings",
                        args.debug,
                    ),
                    resource,
                    module,
                    "resource_or_instance",
                    args.datapoint,
                    device.get("alertDisableStatus") if args.alertStatus else None,
                ))
            if matching_instance:
                rows.extend(threshold_rows(
                alert_items(
                    f"/device/groups/{current_group_id}/datasources/{module_datasource_id}/alertsettings",
                    args.debug,
                ),
                current_group_id,
                module,
                "group",
                args.datapoint,
                device.get("alertDisableStatus") if args.alertStatus else None,
                ))

    output = Path(args.output_path).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        headers = ["id", "resource", "module", "threshold set at", "Expr"]
        if args.alertStatus:
            headers.extend(["alertDisableStatus", "alertDisableStatusMeaning"])
        writer.writerow(headers)
        writer.writerows(rows)
    print(f"Exported {len(rows)} threshold override(s) for {len(device_groups)} device(s) to {output}")


if __name__ == "__main__":
    main()
