#!/usr/bin/env python3
"""List LogicMonitor alert rules and identify devices matching no rule scope.

Coverage here compares the alert rule's device and device-group selectors with
the device inventory. It does not evaluate datasource, instance, datapoint, or
resource-property predicates, so a scope match means a rule could target the
device, not that every alert on it will route through that rule.
"""

import argparse
import csv
import fnmatch
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

from LMToolkit import LMClient

__version__ = "1.2.0"


def get_items(client: LMClient, path: str) -> List[dict]:
    return list(client.paginate(path, {}, page_size=1000))


def as_patterns(value: Any) -> List[str]:
    if value is None or value == "":
        return ["*"]
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        result = []
        for item in value:
            if isinstance(item, dict):
                result.append(str(item.get("name") or item.get("value") or item.get("id") or ""))
            elif item is not None:
                result.append(str(item))
        return result or ["*"]
    return [str(value)]


def matches_any(patterns: Iterable[str], values: Iterable[str]) -> bool:
    values_folded = [value.casefold() for value in values if value]
    for pattern in patterns:
        pattern_folded = pattern.casefold()
        if pattern_folded == "*":
            return True
        if any(fnmatch.fnmatchcase(value, pattern_folded) for value in values_folded):
            return True
    return False


def group_path(group: dict) -> str:
    return str(group.get("fullPath") or group.get("name") or group.get("id") or "")


def device_groups(device: dict, groups_by_id: Dict[str, dict]) -> List[str]:
    raw_ids = device.get("hostGroupIds") or []
    if isinstance(raw_ids, str):
        group_ids = [part.strip() for part in raw_ids.split(",") if part.strip()]
    elif isinstance(raw_ids, list):
        group_ids = [str(part) for part in raw_ids]
    else:
        group_ids = [str(raw_ids)]

    names = []
    for group_id in group_ids:
        group = groups_by_id.get(group_id)
        if group:
            names.extend([group_path(group), str(group.get("name") or ""), group_id])
        else:
            names.append(group_id)
    return list(dict.fromkeys(name for name in names if name))


def rule_matches_device(rule: dict, device: dict, group_names: List[str]) -> bool:
    device_patterns = as_patterns(rule.get("devices"))
    group_patterns = as_patterns(rule.get("deviceGroups"))
    device_names = [
        str(device.get("name") or ""),
        str(device.get("displayName") or ""),
        str(device.get("id") or ""),
    ]
    return matches_any(device_patterns, device_names) and matches_any(group_patterns, group_names)


def build_coverage(devices: List[dict], groups: List[dict], rules: List[dict]) -> List[dict]:
    groups_by_id = {str(group.get("id")): group for group in groups if group.get("id") is not None}
    results = []
    for device in devices:
        group_names = device_groups(device, groups_by_id)
        matches = [rule for rule in rules if rule_matches_device(rule, device, group_names)]
        results.append({
            "deviceId": device.get("id"),
            "deviceName": device.get("displayName") or device.get("name") or "",
            "deviceNameApi": device.get("name") or "",
            "groups": group_names,
            "matchingRuleIds": [rule.get("id") for rule in matches],
            "matchingRuleNames": [rule.get("name") for rule in matches],
            "hasDeviceGroupScopeMatch": bool(matches),
        })
    return results


def csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def write_csv(path: Path, rows: List[dict], fields: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
                writer.writerow({key: csv_value(row.get(key, "")) for key in fields})


def safe_integrations(integrations: List[dict]) -> List[dict]:
    """Keep integration identifiers and labels, never export credentials or payloads."""
    safe_fields = ("id", "name", "type", "enabledStatus", "description")
    return [{key: integration.get(key) for key in safe_fields} for integration in integrations]


def recipient_group_label(group: dict) -> str:
    return str(group.get("groupName") or group.get("name") or group.get("id") or "")


def recipient_group_lookup(groups: List[dict]) -> Dict[str, dict]:
    lookup = {}
    for group in groups:
        for value in (group.get("id"), group.get("groupName"), group.get("name")):
            if value is not None and str(value).strip():
                lookup[str(value).strip().casefold()] = group
    return lookup


def referenced_recipient_group(recipient: dict, lookup: Dict[str, dict]) -> dict:
    """Resolve common group ID/name fields and GROUP-typed recipient addresses."""
    candidates = [recipient.get(key) for key in
                  ("recipientGroupId", "groupId", "recipientGroup", "groupName")]
    if str(recipient.get("type") or "").casefold() in {"group", "recipientgroup", "recipient_group"}:
        candidates.extend((recipient.get("id"), recipient.get("addr"), recipient.get("contact")))
    for candidate in candidates:
        if isinstance(candidate, dict):
            candidate = candidate.get("id") or candidate.get("groupName") or candidate.get("name")
        if candidate is not None:
            group = lookup.get(str(candidate).strip().casefold())
            if group:
                return group
    return {}


def flatten_chain_stages(chains: List[dict], recipient_groups: List[dict] = None) -> List[dict]:
    group_lookup = recipient_group_lookup(recipient_groups or [])
    rows = []
    for chain in chains:
        destinations = chain.get("destinations") or []
        for destination_index, destination in enumerate(destinations, 1):
            period = destination.get("period") or {}
            stages = destination.get("stages") or []
            for stage_index, recipients in enumerate(stages, 1):
                recipients = recipients if isinstance(recipients, list) else []
                if not recipients:
                    recipients = [{}]
                for recipient in recipients:
                    recipient = recipient if isinstance(recipient, dict) else {}
                    recipient_group = referenced_recipient_group(recipient, group_lookup)
                    rows.append({
                        "chainId": chain.get("id"),
                        "chainName": chain.get("name"),
                        "destinationNumber": destination_index,
                        "destinationType": destination.get("type"),
                        "timezone": period.get("timezone"),
                        "startMinutes": period.get("startMinutes"),
                        "endMinutes": period.get("endMinutes"),
                        "weekDays": period.get("weekDays"),
                        "stageNumber": stage_index,
                        "recipientType": recipient.get("type"),
                        "method": recipient.get("method"),
                        "recipient": recipient.get("addr"),
                        "contact": recipient.get("contact"),
                        "recipientGroupId": recipient_group.get("id"),
                        "recipientGroupName": recipient_group_label(recipient_group) if recipient_group else "",
                    })
    return rows


def mermaid_label(value: Any) -> str:
    return str(value if value is not None else "").replace('"', "'").replace("\n", " ")


def build_routing_diagram(
    rules: List[dict], chains: List[dict], integrations: List[dict],
    recipient_groups: List[dict] = None,
) -> str:
    chain_by_id = {str(chain.get("id")): chain for chain in chains}
    integration_names = {str(item.get("name", "")).casefold() for item in integrations}
    group_lookup = recipient_group_lookup(recipient_groups or [])
    lines = ["```mermaid", "flowchart LR", '  resource["Alert generated on resource"]']
    used_chain_ids = set()
    rule_nodes = []

    for index, rule in enumerate(sorted(rules, key=lambda row: (int(row.get("priority") or 0), str(row.get("name") or ""))), 1):
        rule_node = f"rule_{index}"
        chain_id = rule.get("escalatingChainId")
        chain_object = rule.get("escalatingChain")
        if chain_id is None and isinstance(chain_object, dict):
            chain_id = chain_object.get("id")
        chain_node = f"chain_{chain_id}" if chain_id is not None else f"chain_unresolved_{index}"
        chain_name = chain_by_id.get(str(chain_id), {}).get("name")
        if not chain_name and isinstance(chain_object, dict):
            chain_name = chain_object.get("name")
        rule_label = f"Rule {rule.get('id')}: {rule.get('name')} (priority {rule.get('priority')})"
        chain_label = f"Escalation chain {chain_id}: {chain_name or 'unresolved'}"
        lines.append(f'  {rule_node}["{mermaid_label(rule_label)}"]')
        lines.append(f'  {chain_node}["{mermaid_label(chain_label)}"]')
        lines.append(f'  resource -->|"selected matching rule"| {rule_node}')
        lines.append(f"  {rule_node} --> {chain_node}")
        rule_nodes.append(rule_node)
        if chain_id is not None:
            used_chain_ids.add(str(chain_id))

    for chain in chains:
        chain_id = str(chain.get("id"))
        if chain_id not in used_chain_ids:
            chain_node = f"chain_{chain_id}"
            lines.append(
                f'  {chain_node}["Escalation chain {chain_id}: '
                f"{mermaid_label(chain.get('name'))} (not referenced by a rule)\"]"
            )
            used_chain_ids.add(chain_id)

    for chain_id in sorted(used_chain_ids):
        chain = chain_by_id.get(chain_id)
        if not chain:
            continue
        chain_node = f"chain_{chain_id}"
        destinations = chain.get("destinations") or []
        if not destinations:
            terminal = f"chain_{chain_id}_empty"
            lines.append(f'  {terminal}["No destination stages configured"]')
            lines.append(f"  {chain_node} --> {terminal}")
            continue
        for destination_index, destination in enumerate(destinations, 1):
            period = destination.get("period") or {}
            schedule_parts = [str(destination.get("type") or "destination")]
            if period:
                schedule_parts.append(
                    f"{period.get('timezone', 'schedule timezone')}, "
                    f"minutes {period.get('startMinutes')}–{period.get('endMinutes')}, "
                    f"weekdays {period.get('weekDays')}"
                )
            destination_node = f"chain_{chain_id}_destination_{destination_index}"
            lines.append(f'  {destination_node}["Destination {destination_index}: {mermaid_label('; '.join(schedule_parts))}"]')
            lines.append(f"  {chain_node} --> {destination_node}")
            previous_stage_node = destination_node
            for stage_index, recipients in enumerate(destination.get("stages") or [], 1):
                stage_node = f"chain_{chain_id}_destination_{destination_index}_stage_{stage_index}"
                recipient_labels = []
                for recipient in recipients if isinstance(recipients, list) else []:
                    recipient = recipient if isinstance(recipient, dict) else {}
                    method = str(recipient.get("method") or recipient.get("type") or "recipient")
                    addr = str(recipient.get("addr") or recipient.get("contact") or "")
                    recipient_group = referenced_recipient_group(recipient, group_lookup)
                    is_integration = method.casefold() in integration_names
                    label = f"Integration: {method}" if is_integration else method
                    if recipient_group:
                        label = f"Recipient group: {recipient_group_label(recipient_group)}"
                    if addr:
                        label += f" / {addr}"
                    recipient_labels.append(label)
                stage_description = "; ".join(recipient_labels) if recipient_labels else "no recipients configured"
                stage_label = f"Stage {stage_index}: {stage_description}"
                lines.append(f'  {stage_node}["{mermaid_label(stage_label)}"]')
                edge_label = "goes to stage 1" if stage_index == 1 else "escalates if still active/unacknowledged"
                lines.append(f'  {previous_stage_node} -->|"{edge_label}"| {stage_node}')
                previous_stage_node = stage_node

    lines.extend(["```", ""])
    return "\n".join(lines)


def markdown_cell(value: Any) -> str:
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def build_markdown_report(
    rules: List[dict], groups: List[dict], devices: List[dict],
    coverage: List[dict], uncovered: List[dict], chains: List[dict],
    integrations: List[dict], recipient_groups: List[dict] = None,
    integration_error: str = "", recipient_group_error: str = "",
) -> str:
    recipient_groups = recipient_groups or []
    sorted_rules = sorted(
        rules,
        key=lambda row: (int(row.get("priority") or 0), str(row.get("name") or "")),
    )
    lines = [
        "# Alert Rule and Device Group Coverage Audit",
        "",
        f"- Generated: {datetime.now().astimezone().strftime('%d-%m-%Y %H:%M %Z')}",
        f"- Alert rules inspected: {len(rules):,}",
        f"- Device groups inspected: {len(groups):,}",
        f"- Devices inspected: {len(devices):,}",
        f"- Devices with no matching device/group rule scope: {len(uncovered):,}",
        "",
        "## Alert rules",
        "",
        "| Priority | Rule ID | Rule name | Escalation chain | Device groups | Devices |",
        "|---:|---:|---|---|---|---|",
    ]
    chain_by_id = {str(chain.get("id")): chain for chain in chains}
    for rule in sorted_rules:
        chain_id = rule.get("escalatingChainId")
        embedded_chain = rule.get("escalatingChain")
        if chain_id is None and isinstance(embedded_chain, dict):
            chain_id = embedded_chain.get("id")
        chain_name = chain_by_id.get(str(chain_id), {}).get("name")
        values = [rule.get("priority"), rule.get("id"), rule.get("name"),
                  f"{chain_id}: {chain_name or ''}", rule.get("deviceGroups"), rule.get("devices")]
        lines.append("| " + " | ".join(markdown_cell(value) for value in values) + " |")

    lines.extend(["", "## Devices with no matching rule scope", ""])
    if uncovered:
        lines.extend(["| Device ID | Device name | Groups |", "|---:|---|---|"])
        for row in sorted(uncovered, key=lambda item: str(item.get("deviceName") or "").casefold()):
            values = [row.get("deviceId"), row.get("deviceName"), row.get("groups")]
            lines.append("| " + " | ".join(markdown_cell(value) for value in values) + " |")
    else:
        lines.append(f"None. All {len(devices):,} devices match at least one rule's device and group selectors.")

    lines.extend(["", "## Alert routing flow", "", build_routing_diagram(rules, chains, integrations, recipient_groups),
                  "A generated alert follows the matching rule and its configured chain; the diagram shows configuration paths, not that one alert fans out to every rule.",
                  "", "## Escalation chains and stages", "",
                  "| Chain ID | Chain name | Destination | Schedule | Stage | Recipients / integrations |",
                  "|---:|---|---|---|---:|---|"])
    stage_rows = flatten_chain_stages(chains, recipient_groups)
    if stage_rows:
        for row in stage_rows:
            schedule = ""
            if row.get("timezone"):
                schedule = (f"{row.get('timezone')}, minutes {row.get('startMinutes')}–"
                            f"{row.get('endMinutes')}, weekdays {row.get('weekDays')}")
            recipient = row.get("method") or row.get("recipientType") or ""
            if row.get("recipientGroupName"):
                recipient = f"Recipient group: {row['recipientGroupName']}"
            if row.get("recipient"):
                recipient += f" / {row['recipient']}"
            if row.get("contact"):
                recipient += f" / {row['contact']}"
            if not recipient:
                recipient = "(no recipients configured)"
            values = [row.get("chainId"), row.get("chainName"),
                      f"{row.get('destinationNumber')}: {row.get('destinationType')}",
                      schedule, row.get("stageNumber"), recipient]
            lines.append("| " + " | ".join(markdown_cell(value) for value in values) + " |")
    else:
        lines.append("No escalation stages were returned.")

    lines.extend(["", "## Integrations", ""])
    if integrations:
        lines.extend(["| Integration ID | Name | Type | Enabled events | Description |",
                      "|---:|---|---|---|---|"])
        for integration in integrations:
            values = [integration.get("id"), integration.get("name"), integration.get("type"),
                      integration.get("enabledStatus"), integration.get("description")]
            lines.append("| " + " | ".join(markdown_cell(value) for value in values) + " |")
    elif integration_error:
        lines.append(f"Integration records could not be fetched: {markdown_cell(integration_error)}")
    else:
        lines.append("No integrations were returned.")
    lines.append("")
    lines.append("The integrations CSV and this report include metadata only. `integrations.json` contains the full `/setting/integrations` API records, including potentially sensitive URLs, headers, credentials, and payload templates; protect that file and review it before sharing.")

    lines.extend(["", "## Recipient groups", ""])
    if recipient_groups:
        lines.extend(["| Group ID | Group name | Description | Member count | Referenced by an escalation stage |",
                      "|---:|---|---|---:|---|"])
        referenced_ids = {str(row.get("recipientGroupId")) for row in stage_rows if row.get("recipientGroupId") is not None}
        for group in recipient_groups:
            members = group.get("recipients") if isinstance(group.get("recipients"), list) else []
            values = [group.get("id"), recipient_group_label(group), group.get("description"),
                      len(members), "Yes" if str(group.get("id")) in referenced_ids else "No"]
            lines.append("| " + " | ".join(markdown_cell(value) for value in values) + " |")
    elif recipient_group_error:
        lines.append(f"Recipient groups could not be fetched: {markdown_cell(recipient_group_error)}")
    else:
        lines.append("No recipient groups were returned.")
    lines.append("")
    lines.append("`recipient_groups.json` contains the full `/setting/recipientgroups` API records, including member contact details where configured. Treat it as sensitive and review it before sharing.")

    lines.extend([
        "",
        "## Interpretation and limits",
        "",
        "This audit compares device-name and device-group selectors. It does not evaluate datasource, instance, datapoint, resource-property, or attribute filters. A selector match does not guarantee that every alert from a device routes through that rule; review the exported criteria for routing coverage.",
        "",
        "## Output files",
        "",
        "```text",
        "alert-rule-audit/",
        "├── alert_rule_coverage_report.md  (this report)",
        "├── alert_rule_coverage.json",
        "├── alert_rules.csv",
        "├── escalation_chains.csv / escalation_chains.json",
        "├── recipient_groups.csv / recipient_groups.json (full JSON may include personal contact details)",
        "├── integrations.csv (sanitized metadata)",
        "├── integrations.json (full API response; sensitive configuration)",
        "├── device_groups.csv",
        "├── device_rule_coverage.csv",
        "└── devices_without_alert_rule.csv",
        "```",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--creds", default=".env", help="Credentials dotenv file (default: .env)")
    parser.add_argument("--output-dir", default="output/alert-rule-audit", help="Directory for JSON and CSV exports")
    args = parser.parse_args()

    try:
        client = LMClient.from_env(args.creds)
        print("Fetching alert rules...", flush=True)
        rules = get_items(client, "/setting/alert/rules")
        print(f"Fetched {len(rules):,} alert rules.", flush=True)
        print("Fetching escalation chains...", flush=True)
        chains = get_items(client, "/setting/alert/chains")
        print(f"Fetched {len(chains):,} escalation chains.", flush=True)
        recipient_group_error = ""
        print("Fetching recipient groups...", flush=True)
        try:
            recipient_groups = get_items(client, "/setting/recipientgroups")
            print(f"Fetched {len(recipient_groups):,} recipient groups.", flush=True)
        except Exception as exc:
            recipient_groups = []
            recipient_group_error = str(exc)
            print(f"Could not fetch recipient groups: {recipient_group_error}", file=sys.stderr, flush=True)
        integration_error = ""
        print("Fetching integration metadata...", flush=True)
        integrations_raw = []
        try:
            integrations_raw = get_items(client, "/setting/integrations")
            integrations = safe_integrations(integrations_raw)
            print(f"Fetched {len(integrations):,} integrations; full records will be saved privately to JSON.", flush=True)
        except Exception as exc:
            integrations = []
            integration_error = str(exc)
            print(f"Could not fetch integration metadata: {integration_error}", file=sys.stderr, flush=True)
        print("Fetching device groups...", flush=True)
        groups = get_items(client, "/device/groups")
        print(f"Fetched {len(groups):,} device groups.", flush=True)
        print("Fetching devices...", flush=True)
        devices = get_items(client, "/device/devices")
        print(f"Fetched {len(devices):,} devices; matching rule device/group scopes...", flush=True)

        coverage = build_coverage(devices, groups, rules)
        uncovered = [row for row in coverage if not row["hasDeviceGroupScopeMatch"]]
        out_dir = Path(args.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        rule_fields = [
            "id", "name", "priority", "levelStr", "devices", "deviceGroups",
            "datasource", "instance", "datapoint", "resourceProperties",
            "attributeFilters", "escalatingChainId", "escalationInterval",
        ]
        write_csv(out_dir / "alert_rules.csv", rules, rule_fields)
        chain_fields = [
            "chainId", "chainName", "destinationNumber", "destinationType", "timezone",
            "startMinutes", "endMinutes", "weekDays", "stageNumber", "recipientType",
            "method", "recipient", "contact", "recipientGroupId", "recipientGroupName",
        ]
        write_csv(out_dir / "escalation_chains.csv", flatten_chain_stages(chains, recipient_groups), chain_fields)
        recipient_group_rows = []
        for group in recipient_groups:
            recipients = group.get("recipients") if isinstance(group.get("recipients"), list) else []
            if not recipients:
                recipients = [{}]
            for member in recipients:
                member = member if isinstance(member, dict) else {}
                recipient_group_rows.append({
                    "id": group.get("id"), "groupName": recipient_group_label(group),
                    "description": group.get("description"), "recipientType": member.get("type"),
                    "method": member.get("method"), "contact": member.get("contact"),
                    "address": member.get("addr"),
                })
        write_csv(out_dir / "recipient_groups.csv", recipient_group_rows, [
            "id", "groupName", "description", "recipientType", "method", "contact", "address",
        ])
        integration_fields = ["id", "name", "type", "enabledStatus", "description"]
        write_csv(out_dir / "integrations.csv", integrations, integration_fields)
        write_csv(out_dir / "device_groups.csv", groups, [
            "id", "name", "fullPath", "parentId", "appliesTo",
            "disableAlerting", "effectiveAlertEnabled", "alertStatus",
        ])
        write_csv(out_dir / "device_rule_coverage.csv", coverage, [
            "deviceId", "deviceName", "deviceNameApi", "groups",
            "matchingRuleIds", "matchingRuleNames", "hasDeviceGroupScopeMatch",
        ])
        write_csv(out_dir / "devices_without_alert_rule.csv", uncovered, [
            "deviceId", "deviceName", "deviceNameApi", "groups",
        ])
        payload = {
            "coverageBasis": "device and device-group selectors only; does not evaluate datasource, instance, datapoint, resource-property, or attribute filters",
            "alertRules": rules,
            "escalationChains": chains,
            "recipientGroups": recipient_groups,
            "recipientGroupFetchError": recipient_group_error or None,
            "integrations": integrations,
            "integrationFetchError": integration_error or None,
            "deviceGroups": groups,
            "deviceGroupCount": len(groups),
            "deviceCount": len(devices),
            "deviceCoverage": coverage,
            "devicesWithoutMatchingRuleScope": uncovered,
        }
        with (out_dir / "alert_rule_coverage.json").open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False, default=str)
        with (out_dir / "escalation_chains.json").open("w", encoding="utf-8") as handle:
            json.dump(chains, handle, indent=2, ensure_ascii=False, default=str)
        integrations_json_path = out_dir / "integrations.json"
        with integrations_json_path.open("w", encoding="utf-8") as handle:
            json.dump(integrations_raw, handle, indent=2, ensure_ascii=False, default=str)
        os.chmod(integrations_json_path, 0o600)
        recipient_groups_json_path = out_dir / "recipient_groups.json"
        with recipient_groups_json_path.open("w", encoding="utf-8") as handle:
            json.dump(recipient_groups, handle, indent=2, ensure_ascii=False, default=str)
        os.chmod(recipient_groups_json_path, 0o600)
        report_path = out_dir / "alert_rule_coverage_report.md"
        report_path.write_text(
            build_markdown_report(rules, groups, devices, coverage, uncovered,
                                  chains, integrations, recipient_groups, integration_error,
                                  recipient_group_error),
            encoding="utf-8",
        )

        print("\nAlert rules:")
        for rule in sorted(rules, key=lambda row: (row.get("priority", 0), str(row.get("name", "")))):
            print(
                f"  priority={rule.get('priority')} id={rule.get('id')} "
                f"name={rule.get('name')} groups={rule.get('deviceGroups')} "
                f"devices={rule.get('devices')}"
            )
        print(f"\nDevices with no matching device/group rule scope: {len(uncovered):,} of {len(devices):,}")
        if uncovered:
            for row in sorted(uncovered, key=lambda item: str(item["deviceName"]).casefold()):
                print(f"  {row['deviceId']}\t{row['deviceName']}\t{', '.join(row['groups'])}")
        else:
            print("  (none)")
        print(f"\nEscalation chains: {len(chains):,}; recipient groups: {len(recipient_groups):,}; integrations: {len(integrations):,}")
        print(f"CSV/JSON/Markdown reports saved under: {out_dir}")
        print(f"Markdown report: {report_path}")
        print("Scope note: matching indicates device/group scope only; see JSON coverageBasis for limitations.")
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
