# Alert Rule Coverage Audit

## What this tool does

`audit_alert_rule_coverage.py` (version 1.2.0) is a read-only LogicMonitor inventory and routing-scope report. It fetches the account's alert rules, escalation chains, recipient groups, integration metadata, device groups, and devices. It compares each device's name and group membership against the `devices` and `deviceGroups` selectors in every alert rule.

It reports:

- Alert rule names, priorities, device/group selectors, and escalation chain assignments.
- Escalation chain destinations, schedules, stages, and recipients.
- Recipient groups and their configured members, with matching recipient-group references annotated in escalation stages when resolvable.
- Integration metadata referenced by escalation stages.
- Device groups and each device's matching rule scopes.
- Devices that match no alert rule's device/group selectors.
- A Markdown report with a Mermaid flow diagram: resource alert → matching rule → escalation chain → destination → stage.

The API endpoints used are `GET /setting/alert/rules`, `GET /setting/alert/chains`, `GET /setting/recipientgroups`, `GET /setting/integrations`, `GET /device/groups`, and `GET /device/devices`. LogicMonitor documents alert rules and escalation chains as separate resources, with matched alerts dispatched through their configured escalation chain. See [Getting Alert Rule Details](https://www.logicmonitor.com/support/getting-alert-rule-details), [Get Escalation Chains](https://www.logicmonitor.com/support/rest-api-developers-guide/v1/escalation-chains/get-escalation-chains), and [Getting Recipient Group Details](https://www.logicmonitor.com/support/getting-recipient-group-details).

## Coverage limitations

The uncovered-device result checks device-name and group selectors only. It does not evaluate datasource, instance, datapoint, resource-property, or attribute filters, nor does it validate actual notification delivery. A device matching a rule's device/group scope may still not match that rule's other selectors. Treat this as a scope inventory, then review the other exported rule criteria before concluding that alerts route as intended.

`integrations.json` contains the full API records returned by `/setting/integrations`, including potentially sensitive integration URLs, headers, credentials, and payload templates. Protect this file and review it before sharing. The integrations CSV and the Markdown report include only ID, name, type, enabled event types, and description.

`recipient_groups.json` contains the full API records returned by `/setting/recipientgroups`, including member contact details where configured. The recipient groups CSV includes group metadata and one row per member. Both files are written with owner-only permissions. Recipient groups referenced from escalation-chain stages are resolved by ID or name where the stage record exposes a matchable reference; a non-match does not prove the group is unused.

## Requirements

- Python 3 and the packages in `requirements.txt`.
- LogicMonitor API credentials with read access to alert rules, escalation chains, recipient groups, integrations, device groups, and devices.
- A dotenv credentials file containing:

```dotenv
COMPANY=your_logicmonitor_account
ACCESS_ID=your_access_id
ACCESS_KEY=your_access_key
```

Keep the credentials file private; do not attach it to a report or commit it to source control.

## Run

From the directory containing this script:

```bash
source ~/python/bin/activate
python audit_alert_rule_coverage.py --creds .sample --output-dir output/seatrium/alert-rule-audit
```

Replace `.sample` with the path to your private credentials file if you use another filename. If omitted, `--creds` defaults to `.env`; if omitted, `--output-dir` defaults to `output/alert-rule-audit`.

The script prints progress while it fetches each API collection, then prints the alert rules and the uncovered-device count. Each run overwrites the reports in the selected output directory with the latest account data.

## Output files

```text
alert-rule-audit/
├── alert_rule_coverage_report.md  # Summary, rules, uncovered devices, routing diagram
├── alert_rule_coverage.json       # Full inventory and device-to-rule-scope comparison
├── alert_rules.csv                # Rule selectors, priorities, and chain IDs
├── escalation_chains.csv         # Flattened destinations, stages, and recipients
├── escalation_chains.json        # Escalation chain API records
├── recipient_groups.csv          # Group metadata and flattened members
├── recipient_groups.json         # Full API records; may include personal contact details
├── integrations.csv              # Sanitized integration metadata
├── integrations.json             # Full API records; may contain sensitive configuration
├── device_groups.csv             # Device-group inventory
├── device_rule_coverage.csv      # Every device and its matching rule scopes
└── devices_without_alert_rule.csv # Devices with no device/group scope match
```

An empty `devices_without_alert_rule.csv` contains only its header row and means every device matched at least one device/group scope. It does not prove that every datasource, instance, datapoint, or alert will route through a rule.
