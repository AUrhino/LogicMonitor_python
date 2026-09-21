# Create_Portal_AsBuilt.py

Read-only LogicMonitor REST API v3 portal exporter for an engineer-ready as-built evidence pack.

**Version:** 1.04  
**Written by:** Ryan Gillan

## Requirements

Activate the requested Python environment and install the two dependencies:

```bash
source ~/python/bin/activate
python -m pip install requests python-dotenv
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

Useful options:

| Option | Purpose |
|---|---|
| `--version` | Display the script version and exit |
| `--creds-file PATH` | dotenv file; default `.env` |
| `--output PATH` | Custom output folder; default `./as-built-output` |
| `--company NAME` | Override `COMPANY` / `LM_COMPANY` |
| `--access-id ID` / `--access-key KEY` | Override dotenv credentials |
| `--timeout SECONDS` | HTTP timeout; default 60 |
| `--no-raw-json` | Only write CSV and Markdown evidence |
| `--creator-file PATH` | Creator metadata JSON; default `creator.json` |
| `--summary` | Only collect `/setting/companySetting` and write it to Markdown |
| `--debug` | Print API requests and endpoint errors |

Create a Markdown-only company-settings summary without running the full portal
inventory:

```bash
python Create_Portal_AsBuilt.py --creds-file .env --output ./company-summary --summary
```

With `--debug`, the script prints the complete request URL, signed resource path,
HTTP status, response size, row counts, and a redacted error preview. This is the
recommended first diagnostic when CSV files contain only headers.

The debug header also prints the selected portal and resolved credentials-file
path. If another tool returns different data, confirm both tools are querying the
same LogicMonitor company/portal before comparing results.

## Output

The output folder contains:

- `<company>_As_Built.md`: structured handover document with document control, implementation notes, evidence index, validation table, and limitations.
- `csv/`: one flattened CSV per dataset plus `collection_failures.csv`.
- `csv/collection_skipped.csv`: endpoints skipped because a licensed portal feature is not enabled.
- `json/`: redacted raw JSON datasets, useful when CSV flattening hides nested structure.
- `markdown/folder_structure.md`: ASCII trees of LogicMonitor Resource, Website, Dashboard, Report, and Collector groups, starting at each returned root.

Generated Markdown layout:

```text
<output-folder>/
├── <company>_As_Built.md
└── markdown/
    ├── folder_structure.md
    └── numberOfInstancesPerDS/
        └── numberOfInstancesPerDS.*.md
```

The main `*_As_Built.md` file remains at the output root. All auxiliary Markdown
files are written under `markdown/`.

The exporter collects the selected configuration and inventory GET endpoints, plus `/setting/companySetting` and `/alert/stat`. DataSources are collected through the documented per-device sub-resource endpoint. Active alerts, audit logs, dashboard widgets, LogicModule metadata, tracked query groups, diagnostic remediation execution results, API coverage output, and all `_details` expansions are intentionally excluded to control output size. Alert rules and alert statistics remain included. LogicMonitor API permissions and licensed features vary by account; unavailable endpoints do not stop the rest of the export.

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
