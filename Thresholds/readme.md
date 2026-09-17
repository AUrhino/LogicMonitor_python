# Get-LMDevices_and_Thresholds.py

Export LogicMonitor alert-threshold overrides for devices in a device group.

The script checks both:

- Resource/instance-level alert settings:
  `/device/devices/{deviceId}/devicedatasources/{deviceDataSourceId}/instances/{instanceId}/alertsettings`
- Group-level DataSource alert settings:
  `/device/groups/{groupId}/datasources/{dataSourceId}/alertsettings`

Only datapoints where `alertExpr` differs from `globalAlertExpr` are written to the CSV. Empty custom expressions are ignored because they do not represent an explicit override.

## Requirements

- Python 3
- `requests`
- `python-dotenv`
- LogicMonitor API credentials with permission to read devices, DataSources, instances, and alert settings

Install dependencies if needed:

```bash
python3 -m pip install requests python-dotenv
```

## Credentials

The script reads credentials from the environment or a `.env` file in the working directory:

```dotenv
ACCESS_ID=your_logicmonitor_access_id
ACCESS_KEY=your_logicmonitor_access_key
COMPANY=your_logicmonitor_company
```

Alternatively, provide a custom credentials file with `--creds-file`:

```bash
python3 Get-LMDevices_and_Thresholds.py \
  --groupid 17 \
  --creds-file ~/.logicmonitor.env
```

Values from `--creds-file` override the normal environment and `.env` values for that run.

## Basic usage

Running the script without arguments displays the complete help text and examples:

```bash
python3 Get-LMDevices_and_Thresholds.py
```

The group ID is required:

```bash
python3 Get-LMDevices_and_Thresholds.py --groupid 17
```

By default, results are written to `output.csv` in the current directory.

## Arguments

| Argument | Required | Description |
|---|---:|---|
| `--groupid ID` | Yes | LogicMonitor device group ID to inspect. |
| `--subGroups true\|false` | No | Recursively include child groups. Defaults to `false`. |
| `--output PATH` | No | CSV output path. Defaults to `output.csv`. |
| `--creds-file PATH` | No | Load `ACCESS_ID`, `ACCESS_KEY`, and `COMPANY` from a dotenv file. |
| `--resource DISPLAY_NAME` | No | Restrict processing to an exact, case-insensitive resource display name. |
| `--instance NAME` | No | Restrict processing to an exact, case-insensitive DataSource instance name. |
| `--datapoint NAME` | No | Export only an exact, case-insensitive datapoint name. |
| `--alertStatus` | No | Add the raw `alertDisableStatus` and its meaning to the CSV. |
| `--debug` | No | Print API request URLs and HTTP status codes. |
| `--help` | No | Display command help and examples. |

The older `--csv` option is retained as an alias for `--output`.

## Examples

Export all threshold overrides from group `17`:

```bash
python3 Get-LMDevices_and_Thresholds.py --groupid 17
```

Include the group and all child groups:

```bash
python3 Get-LMDevices_and_Thresholds.py --groupid 1 --subGroups true
```

As each group is processed, the script prints its ID, name, description, and direct device count.

Write to a specific file:

```bash
python3 Get-LMDevices_and_Thresholds.py \
  --groupid 17 \
  --output reports/group-17-thresholds.csv
```

Filter to one resource:

```bash
python3 Get-LMDevices_and_Thresholds.py \
  --groupid 17 \
  --resource server01
```

Filter to one resource, instance, and datapoint:

```bash
python3 Get-LMDevices_and_Thresholds.py \
  --groupid 17 \
  --resource server01 \
  --instance Ping \
  --datapoint PingLossPercent
```

Include device alert-disable status and its meaning:

```bash
python3 Get-LMDevices_and_Thresholds.py \
  --groupid 17 \
  --alertStatus
```

Use custom credentials and debug logging:

```bash
python3 Get-LMDevices_and_Thresholds.py \
  --groupid 17 \
  --creds-file ~/.logicmonitor.env \
  --output /tmp/thresholds.csv \
  --debug
```

## Output

The CSV contains these columns:

```text
id,resource,module,threshold set at,Expr
```

- `id`: LogicMonitor datapoint ID.
- `resource`: Resource display name for instance-level results; group ID for group-level results.
- `module`: DataSource name or display name.
- `threshold set at`: `resource_or_instance` or `group`.
- `Expr`: The custom `alertExpr` value.
- `alertDisableStatus`: The three-part status in `GROUP-DEVICE-CHILD` order.
- `alertDisableStatusMeaning`: Plain-English explanation of the status.

The possible standard status values are:

| Value | Meaning |
|---|---|
| `none-disable-none` | Alerting is disabled directly on the device. |
| `disable-none-none` | Alerting is disabled by a device group the device belongs to. |
| `none-none-disable` | Alerting is disabled below the device, such as on a DataSource, instance, or datapoint. |
| `none-none-none` | No alert-disable condition exists at the group, device, or child/sub-resource levels. |

For example:

```csv
id,resource,module,threshold set at,Expr
20799,server01,Ping,resource_or_instance,> 25 75 95
```

## Notes

- Resource and instance filters are exact matches but case-insensitive.
- Group-level settings use the module DataSource ID, while resource instance settings use the device-specific DataSource assignment ID.
- When `--instance` is used, group-level settings are included only for DataSources that contain a matching instance.
- The output directory is created automatically when needed.
- Do not commit credentials files or API keys to source control.

## Author

Ryan Gillan  
Email: ryangillan@gmail.com
