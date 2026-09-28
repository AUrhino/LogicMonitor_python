# LogicMonitor API – Get LM Alerts

`Get-LMAlerts.py` retrieves LogicMonitor alerts through the REST API. It can retrieve account-wide alerts, alerts for one device, or one alert by ID. Results are displayed in the terminal and JSON files are written to `output/`.

Get-LMAlerts version: **1.2.3**  
Group exporter version: **1.0.0**
Alert rule audit version: **1.2.0**

## Requirements

- Python 3.8 or newer
- A LogicMonitor API access ID and API key with permission to read alerts
- Python packages: `requests`, `python-dotenv` (optional: `tabulate`)

## Setup

1. Open a terminal in the directory containing `Get-LMAlerts.py`.
2. Install dependencies:

```bash
python3 -m pip install requests python-dotenv tabulate
```

3. Create a `.env` file in the project root (or pass an alternate file with `--creds PATH`):

```env
ACCESS_ID=your_access_id
ACCESS_KEY=your_access_key
COMPANY=your_company_name
```

Do not commit `.env` or share the access key.

## Quick start

Running without arguments prints the help and examples:

```bash
python3 Get-LMAlerts.py
python3 Get-LMAlerts.py --version
```

## Usage examples

Account-wide alerts:

```bash
python3 Get-LMAlerts.py account
python3 Get-LMAlerts.py account --days-ago 7
python3 Get-LMAlerts.py account --days-ago 30 --counts --save-table
python3 Get-LMAlerts.py account --hours-ago 48 --counts
python3 Get-LMAlerts.py account --counts-verbose --date 23-09-2026 --hour 11 --save-table
python3 Get-LMAlerts.py account --hours-ago 6 --creds ./production.env
python3 Get-LMAlerts.py account --alert-id DS267
python3 Get-LMAlerts.py account --filter "cleared:false" --save-table
python3 Get-LMAlerts.py account --fields "id,severity,monitorObjectName"
python3 Get-LMAlerts.py account --verbose
python3 Get-LMAlerts.py account --page-size 100 --output-dir ./output
python Get-LMAlerts.py account --creds .sample --days-ago 30 --verbose --page-size 1000 --output-dir output/seatrium
python Get-LMAlerts.py account --creds .sample --days-ago 30 --filter 'cleared:true' --verbose --page-size 1000 --output-dir output/seatrium/cleared
python3 Get-LMAlerts.py account --debug --verbose
```

Alerts for a device:

```bash
python3 Get-LMAlerts.py device --device-id 123
python3 Get-LMAlerts.py device --device-id 123 --debug
python3 Get-LMAlerts.py device --device-id 123 --days-ago 14 --need-message
python3 Get-LMAlerts.py device --device-id 123 --hours-ago 12 --alert-id DS267
python3 Get-LMAlerts.py device --device-id 123 --filter "severity:>=3"
python3 Get-LMAlerts.py device --device-id 123 --verbose
python3 Get-LMAlerts.py device --device-id 123 --start 1773581054 --end 1773667454
python3 Get-LMAlerts.py device --device-id 123 --fields "id,severity,monitorObjectName"
python3 Get-LMAlerts.py device --device-id 123 --custom-columns "property=value"
python3 Get-LMAlerts.py device --device-id 123 --bound instances --page-size 100 --output-dir ./output
python3 Get-LMAlerts.py device --device-id 123 --debug --verbose
```

Fetch one alert:

```bash
python3 Get-LMAlerts.py alert --alert-id DS267
python3 Get-LMAlerts.py alert --alert-id DS267 --need-message --save-table
python3 Get-LMAlerts.py alert --alert-id DS267 --verbose
python3 Get-LMAlerts.py alert --alert-id DS267 --fields "id,severity,monitorObjectName"
python3 Get-LMAlerts.py alert --alert-id DS267 --custom-columns "property=value" --output-dir ./output
python3 Get-LMAlerts.py alert --alert-id DS267 --debug --verbose
```

## Output

- Results are printed as a formatted table.
- Account-wide alert tables include the LogicMonitor `monitorObjectId` as `Device ID` and the alert `internalId`.
- JSON responses are saved under `output/`.
- `--save-table` also saves the report as a `.text` file.
- Use `--output-dir PATH` to choose another output directory.
- `--days-ago N` returns alerts from the last N days. For resolved alerts (`cleared:true`), the window uses `endEpoch` (clear time); active alerts use `startEpoch`.
- `--hours-ago N` uses the same active-start/resolved-clear time rule. `--alert-id ID` narrows list mode to a specific alert.
- `--counts` with `--days-ago N` or `--hours-ago N` prints daily counts by alert start hour in `Australia/Sydney`. It includes active and cleared alerts, ignores any `cleared:` condition supplied in `--filter`, and uses columns `00`–`23` for hours and `24` for the daily total. It automatically saves the table as CSV and the matching alert records as JSON; `--save-table` also saves a `.text` copy.
- `--counts-verbose --date DD-MM-YYYY --hour HH` prints all alerts whose `startEpoch` falls within that local date and hour (00–23). This drills into one hourly count bucket and includes active and cleared alerts. It automatically saves matching alert records as CSV and JSON; `--save-table` also saves a `.text` copy.
- Counts queries explicitly request `cleared:*`, because LogicMonitor otherwise returns active alerts only.
- `--creds PATH` loads LogicMonitor credentials from the specified dotenv file (default: `.env`).
- Device mode accepts epoch timestamps with `--start` and `--end`.
- Dates are displayed in the `Australia/Sydney` timezone.
- Add `--debug` to print the API URL, request parameters, response status, and full error traceback when troubleshooting.
- Add `--verbose` to display every field returned by the API. `StartEpoch` is hidden from default views but remains available in verbose output.
- Account alert pagination recognizes LogicMonitor's negative `total` value as an unknown count and continues until the API returns a short page.
- Account-wide queries print progress before each API page request and report the number of records fetched, so a slow query shows that it is still running.
- The account endpoint sorts by `+resourceId` for stable pagination. To collect resolved alerts, use the filter expression `cleared:true` (quote the whole expression for the shell, as shown above). The script also normalizes the UI-style filter `rule:"*",type:"*",cleared:"true"` by removing the redundant wildcard clauses and unquoting the boolean; that raw filter returns no alerts from the API.
- For repeatable analysis instructions and a copy-ready AI prompt, see `How_to_analyse_your_alerts.md`.

## Author

Ryan Gillan  
Email: ryangillan@gmail.com

## Export group monitoring configuration

`export_group_monitoring.py` (version 1.0.0) exports a device group's resources and monitoring configuration to JSON and CSV. It includes child groups by default, datasource definitions and interval fields, datapoints, group-level alert settings, instance-level alert settings, and group/resource properties that may contain interval overrides.

```bash
source ~/python/bin/activate
python export_group_monitoring.py --creds .sample --list-groups
python export_group_monitoring.py --creds .sample --group-id 1234 --output-dir output/seatrium/group-config
python audit_alert_rule_coverage.py --creds .sample --output-dir output/seatrium/alert-rule-audit
```

Use `--group-name "full/group/path"` instead of `--group-id` when the path is unique. Add `--no-subgroups` to limit the export to resources directly assigned to that group. The JSON retains full API records; the CSV flattens datapoints and their group/instance alert settings. Read-only LogicMonitor API access is required.

`audit_alert_rule_coverage.py` exports alert rules, escalation chains/stages, recipient groups, integration metadata, device groups, each device's matching device/group rule scopes, and a list of devices with no matching scope. Each run refreshes CSV/JSON exports and `alert_rule_coverage_report.md`, including a Mermaid alert-to-rule-to-chain-to-stage flow diagram. Escalation stages resolve recipient-group references by ID/name where the API exposes them. `recipient_groups.json` includes complete API records and may contain member contact details; `integrations.json` preserves all fields returned by `/setting/integrations` and may contain credentials, endpoints, headers, or payload templates. Protect both JSON files and review before sharing. This is a scope audit: datasource, instance, datapoint, resource-property, and attribute filters are preserved in rule exports but are not evaluated per device, so a scope match does not guarantee every alert from that device routes through the rule.

Account alert pagination treats negative `total` values from the Alerts endpoint as an unknown count and continues fetching until a short page is returned.
