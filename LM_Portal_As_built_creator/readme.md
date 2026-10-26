# Create_Portal_AsBuilt.py

Read-only LogicMonitor REST API v3 portal exporter for an engineer-ready as-built evidence pack.

**Version:** 1.13  
**Written by:** Ryan Gillan

## Requirements

Activate the requested Python environment and install the dependencies:

```bash
source ~/python/bin/activate
python -m pip install requests python-dotenv markdown
```

Create a `.env` file in the working directory, or provide another dotenv file with:

```dotenv
ACCESS_ID=your_logicmonitor_access_id
ACCESS_KEY=your_logicmonitor_access_key
COMPANY=your_logicmonitor_company
```

The API identity should be read-only and have access to the portal objects that need to be documented. Secret values returned by the API are redacted before being written.
Every request sends `X-Version: 3` and uses LogicMonitor REST API v3 LMv1 signing.

## Usage

Running the script without arguments prints its help and examples without making
any API requests:

```bash
python Create_Portal_AsBuilt.py
```

Run from any directory:

```bash
python "/Users/ryan.gillan/Documents/Python_Testing/Handy Scripts/As_Built/Create_Portal_AsBuilt.py" \
  --creds-file .env \
  --output ./customer-as-built
```

Credentials may be overridden for one run:

```bash
python Create_Portal_AsBuilt.py --company acme --access-id ID --access-key KEY --output ./acme-as-built
```

## Complete command-line option reference

### General options

| Option | Purpose |
|---|---|
| `-h`, `--help` | Display help, available options, and examples |
| `--version` | Display the script version and exit |
| `--creds-file PATH`, `--env PATH` | Select the dotenv credentials file; default `.env` |
| `--output PATH`, `-o PATH` | Select the output folder; default `./as-built-output` |
| `--company NAME` | Override `COMPANY` or `LM_COMPANY` from dotenv |
| `--access-id ID` | Override `ACCESS_ID` or `LM_ACCESS_ID` from dotenv |
| `--access-key KEY` | Override `ACCESS_KEY` or `LM_ACCESS_KEY` from dotenv |
| `--timeout SECONDS` | Set the HTTP request timeout; default `60` seconds |
| `--creator-file PATH` | Select the document creator metadata file; default `creator.json` |
| `--company-image PATH` | Select the report logo; default `company.png` |
| `--csv-order-file PATH` | Select CSV column-order definitions; default `csv_column_order.txt` |
| `--no-raw-json`, `--no-json` | Do not write raw JSON evidence files |
| `--summary` | Only collect `/setting/companySetting` and write the summary Markdown report |
| `--debug` | Print request URLs, signed paths, response details, row counts, and non-fatal errors |

### Category exclusion options

These switches disable related groups of API collections.

| Option | Sections skipped |
|---|---|
| `--no-modules` | All LogicModule-related sections |
| `--no-reports` | Reports and report groups |
| `--no-dashboards`, `--no-dashbourds` | Dashboards and dashboard groups |
| `--no-users` | Users |
| `--no-devices` | Devices and the derived Services and DataSources collections |
| `--no-collectors` | Collectors, collector groups, collector versions, and collector upgrade history |

### Individual API-section exclusion options

| Option | Section skipped |
|---|---|
| `--no-company-settings` | Company settings |
| `--no-alert-statistics` | Alert statistics and versions |
| `--no-device-groups` | Device groups |
| `--no-unmonitored-devices` | Unmonitored devices |
| `--no-collector-groups` | Collector groups |
| `--no-collector-versions` | Collector versions |
| `--no-collector-upgrade-history` | Collector upgrade history |
| `--no-alert-rules` | Alert rules |
| `--no-escalation-chains` | Escalation chains |
| `--no-action-chains` | Action chains |
| `--no-action-rules` | Action rules |
| `--no-integrations` | Integrations |
| `--no-api-tokens` | API tokens |
| `--no-roles` | Roles |
| `--no-access-groups` | Access groups |
| `--no-dashboard-groups` | Dashboard groups |
| `--no-report-groups` | Report groups |
| `--no-netscans` | NetScans |
| `--no-websites` | Websites |
| `--no-website-groups` | Website groups |
| `--no-website-checkpoints` | Website checkpoints |
| `--no-logpipelines` | Log pipelines |
| `--no-logpipeline-processors` | Log pipeline processors |
| `--no-log-sources` | Log Sources |
| `--no-log-partitions` | Log partitions |
| `--no-log-retentions` | Log retention settings |
| `--no-log-query-groups` | Log query groups |
| `--no-datasource-modules` | DataSource modules |
| `--no-configsource-modules` | ConfigSource modules |
| `--no-eventsource-modules` | EventSource modules |
| `--no-propertysource-rules` | PropertySource rules |
| `--no-topology-sources` | Topology Sources |
| `--no-job-monitors` | Job monitors |
| `--no-applies-to-functions` | AppliesTo functions |
| `--no-oids` | OIDs |
| `--no-recipient-groups` | Recipient groups |
| `--no-sdts` | Scheduled downtime records |
| `--no-ops-notes` | Ops Notes |
| `--no-diagnostic-sources` | Diagnostic Sources |
| `--no-remediation-sources` | Remediation Sources |
| `--no-diagnostic-remediation-assignments` | Diagnostic/remediation assignments |
| `--no-metrics-usage` | Metrics usage |
| `--no-metrics-summary` | Metrics summary |
| `--no-contract-info` | Contract information |
| `--no-focus-cost-usage` | FOCUS cost usage |
| `--no-cost-recommendations` | Cost recommendations |
| `--no-cost-recommendation-categories` | Cost recommendation categories |
| `--no-aws-external-id` | AWS external ID |
| `--no-aws-account-id` | AWS account ID |
| `--no-external-api-stats` | External API statistics |
| `--no-device-delta` | Device delta information |

### Generated-section exclusion options

| Option | Generated section skipped |
|---|---|
| `--no-services` | Filtered Services dataset |
| `--no-datasources` | Per-device DataSources evidence |
| `--no-group-alert-settings` | Group DataSource alert-setting traversal and evidence |
| `--no-alert-routing-flow` | `markdown/alert_routing_flow.md` |
| `--no-folder-structure` | `markdown/folder_structure.md` |
| `--no-number-of-instances-per-ds` | Extracted `markdown/numberOfInstancesPerDS/` files |
| `--no-cost-recommendation-items` | Per-recommendation `/cost-optimization/recommendations/{id}` evidence |
| `--no-cloud-endpoints` | `markdown/cloud_endpoints.md` |
| `--no-portal-logos` | Portal heading/login logo image evidence |

Create a Markdown-only company-settings summary without running the full portal
inventory:

```bash
python Create_Portal_AsBuilt.py --creds-file .env --output ./company-summary --summary
```

With `--debug`, the script prints the complete request URL, signed resource path,
HTTP status, response size, row counts, and a redacted error preview. This is the
recommended first diagnostic when CSV files contain only headers.

If LogicMonitor returns HTTP `429 Too Many Requests`, the exporter waits two
seconds, generates a fresh LMv1 signature, and retries the request. It performs
up to five retries before recording the endpoint as a collection failure. Debug
mode prints each rate-limit wait and retry count.

The debug header also prints the selected portal and resolved credentials-file
path. If another tool returns different data, confirm both tools are querying the
same LogicMonitor company/portal before comparing results.

## Output

The output folder contains:

- `<company>_As_Built.md`: structured handover document with document control, implementation notes, evidence index, validation table, and limitations.
- `<company>_As_Built.html`: standalone rendered HTML version of the main report, suitable for browser review and printing.
- `csv/`: one flattened CSV per dataset plus `collection_failures.csv`.
- `csv/collection_skipped.csv`: endpoints skipped because a licensed portal feature is not enabled.
- `json/`: redacted raw JSON datasets, useful when CSV flattening hides nested structure.
- `images/portal_heading_logo.<ext>`: configured company/heading logo from `/setting/logos/company`.
- `images/portal_login_logo.<ext>`: configured login logo from `/setting/logos/login`.
- `markdown/folder_structure.md`: ASCII trees of LogicMonitor Resource, Website, Dashboard, Report, and Collector groups, starting at each returned root.
- `markdown/cloud_endpoints.md`: v3 cloud endpoint coverage, cloud account groups, and the safety status of POST/PATCH operations.
- Every generated `.md` file has a matching `.html` companion in the same folder.

Generated Markdown layout:

```text
<output-folder>/
├── <company>_As_Built.md
├── <company>_As_Built.html
├── images/
│   ├── portal_heading_logo.<ext>
│   └── portal_login_logo.<ext>
└── markdown/
    ├── cloud_endpoints.md / cloud_endpoints.html
    ├── folder_structure.md / folder_structure.html
    └── numberOfInstancesPerDS/
        └── numberOfInstancesPerDS.*.md / numberOfInstancesPerDS.*.html
```

The main `*_As_Built.md` file remains at the output root. All auxiliary Markdown
files are written under `markdown/`.

HTML is generated locally from the Markdown using Python-Markdown with table,
fenced-code, and list support. The HTML files contain embedded styling and do
not require an external conversion service. Images remain relative to the HTML
file, so keep `company.png` beside the main report when moving the output.

The full export and `--summary` mode also capture the portal's configured
heading/company logo and login logo. Both images are embedded in the generated
Markdown and HTML reports, and `csv/portal_logos.csv` records their source
endpoints, content types, sizes, and output paths. Use `--no-portal-logos` to
disable this collection.

When a portal heading/company logo is successfully retrieved, it replaces the
default `company.png` branding at the top of the generated Markdown and HTML
reports. If the portal logo is unavailable or logo collection is disabled,
`company.png` remains the fallback.

Normalized Properties are shown in Portal Settings but are not available through
the supported external REST API v3. The known query is the internal v4
`POST /normalizedProperties/filter` operation. LogicMonitor rejects external
API-token requests to v4 with `Unsupported API Version`, so the exporter records
this limitation instead of producing misleading empty evidence.

The exporter collects the selected configuration and inventory GET endpoints, plus `/setting/companySetting` and `/alert/stat`. DataSources are collected through the documented per-device sub-resource endpoint. Active alerts, audit logs, dashboard widgets, LogicModule metadata, tracked query groups, diagnostic remediation execution results, API coverage output, and all `_details` expansions are intentionally excluded to control output size. Alert rules and alert statistics remain included. LogicMonitor API permissions and licensed features vary by account; unavailable endpoints do not stop the rest of the export.

Cloud collection includes AWS identifiers, cloud cost recommendation categories
and recommendations, each returned recommendation's documented per-ID endpoint,
contract information, FOCUS cost usage, and the standard device/device-group
inventories. The generated `markdown/cloud_endpoints.md` records the status and
evidence for every requested cloud endpoint. Provider validation/discovery POST
operations and the device-group PATCH operation are documented there but are not
executed, preserving the exporter's GET-only behavior. Per-device and per-group
detail expansion remains omitted to avoid duplicating the list inventories.

Services are collected separately from `/device/devices` using the API filter
`deviceType:"6"` and are rendered directly after Devices with the fields `id`,
`name`, `displayName`, `description`, `deviceType`, and `hostStatus`.

OIDs are collected from `/setting/oids` with `sort=+id` and rendered with the
fields `id`, `oid`, and `categories`. Device `createdOn` and `updatedOn` epoch
values are rendered in local time using the `date_format` from `creator.json`.
Dashboards use `/dashboard/dashboards` with `sort=+id`; per-device DataSources
continue to use the LogicMonitor device DataSources subresource.

DataSources are retained as CSV/JSON evidence and in the Exported evidence index,
but their high-volume detail section is omitted from the main Markdown report.

The report includes a Portal Monitoring section after Devices. It locates the
resource named `<company>.logicmonitor.com`, displays its ID, name, and display
name, and links to LogicMonitor's portal-monitoring guidance.

The exporter copies `company.png` into the output root and places it at the top
left of full and summary Markdown reports. Use `--company-image /path/logo.png`
to select another source image. If the default image is not in the current
directory, the exporter also checks beside `Create_Portal_AsBuilt.py`.

The exporter also traverses each visible device group's DataSources and
group-level alert settings, following the read-only logic used by
`export_group_monitoring.py`. It writes `group_alert_settings.csv` and JSON
evidence, then builds `markdown/alert_routing_flow.md` from those overrides,
alert rules, escalation chains and destinations, action rules, and action
chains. The high-volume group-alert rows are not repeated in the main report.

## Excluding sections

Use category switches to reduce API calls and output size:

```bash
python Create_Portal_AsBuilt.py --output ./customer-as-built \
  --no-modules \
  --no-reports \
  --no-dashboards \
  --no-users \
  --no-devices \
  --no-collectors
```

`--no-dashbourds` is accepted as an alias for `--no-dashboards`, and
`--no-json` is accepted as an alias for `--no-raw-json`.

Every individual API section also has a generated kebab-case exclusion option,
including `--no-alert-rules`, `--no-integrations`, `--no-device-groups`,
`--no-websites`, `--no-netscans`, and similar options shown by `--help`.
Generated sections can be disabled with `--no-services`, `--no-datasources`,
`--no-group-alert-settings`, `--no-alert-routing-flow`,
`--no-folder-structure`, `--no-number-of-instances-per-ds`,
`--no-cost-recommendation-items`, `--no-cloud-endpoints`, and
`--no-portal-logos`.

## CSV column ordering

The exporter automatically loads `csv_column_order.txt` from the current
directory or from beside `Create_Portal_AsBuilt.py`. The supplied definitions
set the requested leading column order for:

- `action_rules.csv`
- `alert_rules.csv`
- `applies_to_functions.csv`
- `device_groups.csv`
- `devices.csv`
- `collectors.csv`

Any additional fields returned by the API are appended alphabetically after the
defined columns so that ordering changes do not discard data. Use
`--csv-order-file /path/custom-order.txt` to select another definition file.
Each schema starts with a CSV filename on its own line, followed by one or more
comma- or tab-separated field lines.

After an export, the console summary lists each failed collection with its API
endpoint and error, lists disabled-feature skips separately, and recommends the
main report, folder hierarchy, collection diagnostics, devices, collectors, and
integrations files for review.

The Markdown document gives every dataset its own heading and renders its selected fields in a compact table. Resource groups are represented by the hierarchy in `markdown/folder_structure.md`. Company settings and alert statistics are rendered as complete key/value tables.

To keep the main document readable, `numberOfInstancesPerDS.*` company settings
are removed from the main table and written as individual Markdown files such as
`markdown/numberOfInstancesPerDS/numberOfInstancesPerDS.HTTP-.md`. The Exported
Evidence section links to the folder once rather than listing every extracted
setting file. High-volume operational datasets—including
per-device DataSources retain their
row counts and CSV/JSON evidence links but do not render every row in Markdown.

Key v3 endpoints include:

```text
/device/devices
/device/groups
/setting/collector/collectors
/setting/collector/collectors/versions
/setting/alert/rules
/setting/alert/chains
/setting/integrations
/dashboard/dashboards
/setting/admins
/setting/roles
/setting/accessgroup
/report/reports
/setting/netscans
/website/websites
/logpipelines
```

Integration evidence is written to:

- `csv/integrations.csv`
- Matching redacted files under `json/`, unless `--no-raw-json` is used.

## Safety and handover notes

- This script performs GET requests only.
- Do not commit generated customer output to source control.
- Review the Markdown and add project dates, design rationale, network requirements, validation evidence, runbooks, support contacts, known issues, and open actions.
- Never add passwords, SNMP communities, API keys, tokens, private keys, or bearer tokens to the Markdown document.
