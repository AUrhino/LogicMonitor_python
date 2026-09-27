#!/usr/bin/env python3
"""Export LogicMonitor collection and alert configuration for a device group.

The JSON preserves complete API records. The CSV is a flattened inventory of
datasource/instance datapoints and includes the source records for thresholds,
collection intervals, and effective alert settings where the API exposes them.
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from LMToolkit import LMClient

__version__ = "1.0.0"


def payload_data(payload: Any) -> Any:
    return payload.get("data", payload) if isinstance(payload, dict) else payload


def item_list(payload: Any) -> List[Dict[str, Any]]:
    data = payload_data(payload)
    if isinstance(data, dict):
        rows = data.get("items", [])
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def get_items(client: LMClient, path: str, params: Optional[dict] = None) -> List[dict]:
    return list(client.paginate(path, params or {}, page_size=1000))


def group_identifier(group: dict) -> Any:
    return group.get("id", group.get("value"))


def group_path(group: dict) -> str:
    return str(group.get("fullPath") or group.get("name") or group_identifier(group))


def get_collection_interval(record: Optional[dict]) -> Any:
    if not isinstance(record, dict):
        return None
    return record.get("collectInterval", record.get("collectionInterval"))


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_.") or "group"


def resolve_group(groups: List[dict], group_id: Optional[str], group_name: Optional[str]) -> dict:
    if group_id:
        matches = [g for g in groups if str(group_identifier(g)) == str(group_id)]
    else:
        matches = [g for g in groups if group_path(g).casefold() == group_name.casefold()
                   or str(g.get("name", "")).casefold() == group_name.casefold()]
    if len(matches) != 1:
        if not matches:
            raise ValueError("No matching group. Use --list-groups to inspect IDs and paths.")
        found = ", ".join(f"{group_path(g)} (id={group_identifier(g)})" for g in matches)
        raise ValueError(f"Group name is ambiguous; use --group-id. Matches: {found}")
    return matches[0]


def descendants(root: dict, groups: List[dict]) -> List[dict]:
    by_parent: Dict[str, List[dict]] = {}
    for group in groups:
        by_parent.setdefault(str(group.get("parentId", "")), []).append(group)
    result, seen, todo = [], set(), [root]
    while todo:
        current = todo.pop(0)
        gid = str(group_identifier(current))
        if gid in seen:
            continue
        seen.add(gid)
        result.append(current)
        todo.extend(by_parent.get(gid, []))
    return result


def source_datapoints(source: dict) -> List[dict]:
    for key in ("datapoints", "dataPoints", "dataPointsConfig"):
        value = source.get(key)
        if isinstance(value, list):
            return [point for point in value if isinstance(point, dict)]
    return []


def alertsettings_by_point(payload: Any) -> Dict[str, dict]:
    rows = item_list(payload)
    result = {}
    for row in rows:
        name = row.get("dataPointName") or row.get("name")
        if name:
            result[str(name).casefold()] = row
    return result


def row_for_point(context: dict, point: dict, settings: dict) -> dict:
    name = point.get("name") or point.get("dataPointName") or point.get("dataPoint") or ""
    setting = settings.get(str(name).casefold(), {})
    return {
        "groupPath": context.get("groupPath"),
        "groupId": context.get("groupId"),
        "deviceId": context.get("deviceId"),
        "deviceName": context.get("deviceName"),
        "deviceDatasourceId": context.get("deviceDatasourceId"),
        "datasourceId": context.get("datasourceId"),
        "datasourceName": context.get("datasourceName"),
        "instanceId": context.get("instanceId"),
        "instanceName": context.get("instanceName"),
        "dataPointId": point.get("id", point.get("dataPointId")),
        "dataPointName": name,
        "dataType": point.get("dataType", point.get("type")),
        "description": point.get("description"),
        "datasourceCollectionInterval": context.get("datasourceCollectionInterval"),
        "deviceDatasourceCollectionInterval": context.get("deviceDatasourceCollectionInterval"),
        "instanceAlertExpr": setting.get("alertExpr"),
        "instanceDisableAlerting": setting.get("disableAlerting"),
        "groupAlertExpr": context.get("groupAlertExpr"),
        "groupDisableAlerting": context.get("groupDisableAlerting"),
        "datapointConfig": json.dumps(point, ensure_ascii=False, default=str),
        "instanceAlertSetting": json.dumps(setting, ensure_ascii=False, default=str) if setting else "",
        "groupAlertSetting": context.get("groupAlertSetting", ""),
    }


def export(client: LMClient, root: dict, groups: List[dict], include_subgroups: bool) -> dict:
    selected_groups = descendants(root, groups) if include_subgroups else [root]
    out = {
        "group": root,
        "includedSubgroups": selected_groups,
        "groupDatasources": [],
        "devices": [],
        "errors": [],
    }
    group_settings = {}
    # Group-level datasource membership and alert thresholds, including overrides.
    for group in selected_groups:
        gid = group_identifier(group)
        try:
            group["exportedProperties"] = get_items(client, f"/device/groups/{gid}/properties")
        except Exception as exc:
            group["exportedProperties"] = []
            out["errors"].append({"scope": "group-properties", "groupId": gid, "error": str(exc)})
        try:
            group_sources = get_items(client, f"/device/groups/{gid}/datasources")
        except Exception as exc:
            out["errors"].append({"scope": "group-datasources", "groupId": gid, "error": str(exc)})
            continue
        for group_source in group_sources:
            dsid = group_source.get("dataSourceId", group_source.get("id"))
            config = None
            if dsid is not None:
                try:
                    config = payload_data(client.get(f"/device/groups/{gid}/datasources/{dsid}/alertsettings"))
                except Exception as exc:
                    out["errors"].append({"scope": "group-alertsettings", "groupId": gid,
                                          "datasourceId": dsid, "error": str(exc)})
            out["groupDatasources"].append({"group": group, "datasource": group_source,
                                             "alertsettings": config})
            group_settings[(str(gid), str(dsid))] = {
                "raw": config,
                "byPoint": alertsettings_by_point(config),
            }

    seen_devices = set()
    for group in selected_groups:
        gid = group_identifier(group)
        try:
            devices = get_items(client, f"/device/groups/{gid}/devices")
        except Exception as exc:
            out["errors"].append({"scope": "group-devices", "groupId": gid, "error": str(exc)})
            continue
        for device in devices:
            did = device.get("id", device.get("deviceId"))
            if did is None or str(did) in seen_devices:
                continue
            seen_devices.add(str(did))
            try:
                device_properties = get_items(client, f"/device/devices/{did}/properties")
            except Exception as exc:
                device_properties = []
                out["errors"].append({"scope": "device-properties", "deviceId": did, "error": str(exc)})
            device_record = {"groupPath": group_path(group), "device": device,
                             "properties": device_properties, "datasources": []}
            try:
                device_sources = get_items(client, f"/device/devices/{did}/devicedatasources")
            except Exception as exc:
                out["errors"].append({"scope": "device-datasources", "deviceId": did, "error": str(exc)})
                out["devices"].append(device_record)
                continue
            for device_source in device_sources:
                hdsid = device_source.get("id", device_source.get("deviceDatasourceId"))
                dsid = device_source.get("dataSourceId", device_source.get("datasourceId"))
                source_config = None
                if dsid is not None:
                    try:
                        source_config = payload_data(client.get(f"/setting/datasources/{dsid}"))
                    except Exception as exc:
                        out["errors"].append({"scope": "datasource-definition", "deviceId": did,
                                              "datasourceId": dsid, "error": str(exc)})
                ds_name = (device_source.get("dataSourceName") or device_source.get("name")
                           or (source_config or {}).get("name", ""))
                ds_record = {"datasource": device_source, "definition": source_config, "instances": []}
                if hdsid is not None:
                    try:
                        instances = get_items(client, f"/device/devices/{did}/devicedatasources/{hdsid}/instances")
                    except Exception as exc:
                        out["errors"].append({"scope": "instances", "deviceId": did,
                                              "deviceDatasourceId": hdsid, "error": str(exc)})
                        instances = []
                    for instance in instances:
                        iid = instance.get("id", instance.get("instanceId"))
                        thresholds = None
                        if iid is not None:
                            try:
                                thresholds = payload_data(client.get(
                                    f"/device/devices/{did}/devicedatasources/{hdsid}/instances/{iid}/alertsettings"))
                            except Exception as exc:
                                out["errors"].append({"scope": "instance-alertsettings", "deviceId": did,
                                                      "instanceId": iid, "error": str(exc)})
                        instance_record = {"instance": instance, "alertsettings": thresholds}
                        ds_record["instances"].append(instance_record)
                ds_record["flattenedDatapoints"] = []
                points = source_datapoints(source_config or {})
                for instance_record in ds_record["instances"]:
                    setting_map = alertsettings_by_point(instance_record.get("alertsettings"))
                    group_setting = group_settings.get((str(gid), str(dsid)), {})
                    context = {
                        "groupPath": group_path(group), "groupId": gid, "deviceId": did,
                        "deviceName": device.get("displayName", device.get("name")),
                        "deviceDatasourceId": hdsid, "datasourceId": dsid, "datasourceName": ds_name,
                        "instanceId": instance_record["instance"].get("id"),
                        "instanceName": instance_record["instance"].get("name"),
                        "datasourceCollectionInterval": get_collection_interval(source_config),
                        "deviceDatasourceCollectionInterval": get_collection_interval(device_source),
                        "groupAlertExpr": group_point_setting.get("alertExpr"),
                        "groupDisableAlerting": group_point_setting.get("disableAlerting"),
                        "groupAlertSetting": json.dumps(group_setting.get("raw"), ensure_ascii=False,
                                                         default=str) if group_setting.get("raw") is not None else "",
                    }
                    for point in points:
                        point_name = point.get("name") or point.get("dataPointName") or point.get("dataPoint") or ""
                        group_point_setting = group_setting.get("byPoint", {}).get(str(point_name).casefold(), {})
                        context["groupAlertExpr"] = group_point_setting.get("alertExpr")
                        context["groupDisableAlerting"] = group_point_setting.get("disableAlerting")
                        ds_record["flattenedDatapoints"].append(row_for_point(context, point, setting_map))
                device_record["datasources"].append(ds_record)
            out["devices"].append(device_record)
    return out


def write_outputs(data: dict, out_dir: Path) -> tuple:
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = safe_name(group_path(data["group"]))
    json_path = out_dir / f"{prefix}_monitoring_config.json"
    csv_path = out_dir / f"{prefix}_datapoints_thresholds.csv"
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    rows = [row for device in data["devices"] for ds in device["datasources"]
            for row in ds.get("flattenedDatapoints", [])]
    fields = list(rows[0].keys()) if rows else [
        "groupPath", "groupId", "deviceId", "deviceName", "deviceDatasourceId", "datasourceId",
        "datasourceName", "instanceId", "instanceName", "dataPointId", "dataPointName",
        "dataType", "description", "datasourceCollectionInterval", "deviceDatasourceCollectionInterval",
        "instanceAlertExpr", "instanceDisableAlerting", "groupAlertExpr", "groupDisableAlerting",
        "datapointConfig", "instanceAlertSetting", "groupAlertSetting"]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return json_path, csv_path, len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--creds", default=".env", help="Credentials dotenv file (default: .env)")
    parser.add_argument("--group-id", help="LogicMonitor device group ID")
    parser.add_argument("--group-name", help="Exact group name or full path")
    parser.add_argument("--list-groups", action="store_true", help="List visible group IDs and paths")
    parser.add_argument("--no-subgroups", action="store_true", help="Only include resources assigned directly to this group")
    parser.add_argument("--output-dir", default="output/group-config", help="Directory for JSON and CSV exports")
    args = parser.parse_args()
    if not args.list_groups and bool(args.group_id) == bool(args.group_name):
        parser.error("provide exactly one of --group-id or --group-name (or use --list-groups)")
    try:
        client = LMClient.from_env(args.creds)
        groups = get_items(client, "/device/groups")
        if args.list_groups:
            for group in sorted(groups, key=group_path):
                print(f"{group_identifier(group)}\t{group_path(group)}")
            return 0
        root = resolve_group(groups, args.group_id, args.group_name)
        data = export(client, root, groups, include_subgroups=not args.no_subgroups)
        json_path, csv_path, point_count = write_outputs(data, Path(args.output_dir))
        print(f"Group: {group_path(root)} (id={group_identifier(root)})")
        print(f"Resources: {len(data['devices'])}; datapoint rows: {point_count}; API issues: {len(data['errors'])}")
        print(f"JSON: {json_path}\nCSV: {csv_path}")
        if data["errors"]:
            print("Some endpoint results were unavailable; see the JSON errors array.", file=sys.stderr)
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
