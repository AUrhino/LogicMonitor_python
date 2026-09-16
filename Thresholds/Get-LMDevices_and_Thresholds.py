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
    parser.add_argument(
        "--creds-file", metavar="PATH",
        help="Load ACCESS_ID, ACCESS_KEY, and COMPANY from a dotenv credentials file.",
    )
    parser.add_argument("--resource", metavar="DISPLAY_NAME", help="Only process this resource display name.")
    parser.add_argument("--instance", metavar="NAME", help="Only process this DataSource instance name.")
    parser.add_argument("--datapoint", metavar="NAME", help="Only export this datapoint name.")
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


def threshold_rows(items, resource, module, threshold_level, datapoint_filter=None):
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
        rows.append([
            item.get("dataPointId"),
            resource,
            module,
            threshold_level,
            expression,
        ])
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

    try:
        devices = get_items(
            f"/device/groups/{args.groupid}/devices",
            {"size": 1000, "offset": 0},
            args.debug,
        )
    except requests.RequestException as error:
        raise SystemExit(f"Unable to fetch devices for group {args.groupid}: {error}")

    rows = []
    for device in devices:
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
                ))
            if matching_instance:
                rows.extend(threshold_rows(
                alert_items(
                    f"/device/groups/{args.groupid}/datasources/{module_datasource_id}/alertsettings",
                    args.debug,
                ),
                args.groupid,
                module,
                "group",
                args.datapoint,
                ))

    output = Path(args.output_path).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "resource", "module", "threshold set at", "Expr"])
        writer.writerows(rows)
    print(f"Exported {len(rows)} threshold override(s) for {len(devices)} device(s) to {output}")


if __name__ == "__main__":
    main()
