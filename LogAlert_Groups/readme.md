# LogicMonitor LogAlert Groups / LogAlerts Utility

**Version:** 1.03  
**Created by:** Ryan Gillan

## Commands

| Option | Purpose |
|---|---|
| `--show-tree` | GET `/logpipelines` and `/logpipelines/processors` and render an ASCII tree |
| `--backup PATH` | Back up all LogAlert Groups and LogAlerts to JSON |
| `--create PATH` | POST one object |
| `--restore PATH` | Recreate every object in a backup, remapping pipeline IDs |
| `--create-kind pipeline\|processor` | Specify the object type for `--create` |
| `--create-id ID` | Select one object from a backup for `--create` |
| `--creds-file PATH` | Select an alternate dotenv file; default is `.env` |
| `--partition NAME` | Partition used when backup pipeline partition metadata is absent (default: `default`) |
| `--debug` | Print safe HTTP diagnostics |
| `--version` | Print `1.02` and creator |
| `--html PATH` | Generate an HTML report with horizontally resizable columns |
| `--raw` | Print full GET JSON |

## Credentials

Default:

```text
.env
```

Override:

```text
python3 Get-LMLogAlerts.py --creds-file .sample --show-tree
```

The credentials file should contain:

```text
ACCESS_ID=...
ACCESS_KEY=...
COMPANY=...
```

Optional:

```text
LM_BASE_URL=https://sample.logicmonitor.com/santaba/rest
```

## Backup

Create a complete backup:

```text
python3 Get-LMLogAlerts.py \
  --creds-file .sample \
  --backup output/sample.json \
  --debug
```

The backup contains:

```text
logpipelines
processors
rawResponses
```


## Restore

`--restore` is now implemented.

Use:

```text
python3 Get-LMLogAlerts.py \
  --creds-file .sample \
  --restore output/sample.json \
  --restore-results output/restore-results.json \
  --debug
```

Restore order is:

```text
1. POST /logpipelines for every LogAlert Group
2. Capture each old pipeline ID and its newly-created ID
3. POST /logpipelines/processors for every LogAlert
4. Replace the processor's old pipelineId with the new pipeline ID
```

For example:

```text
Backup:
  pipeline ID 22
    processor 78 -> pipelineId 22
```

can become:

```text
Destination:
  pipeline ID 101
    processor 150 -> pipelineId 101
```

The original GET-generated `id` is not sent in a create request.

### Important

`--restore` is **CREATE ONLY**.

It does not:

```text
DELETE
PUT
PATCH
```

existing configuration.

Therefore, don't use `--restore` against an account where you are expecting an existing configuration to be replaced. It will create new objects.

The restore results file records:

```text
old pipeline ID
new pipeline ID
old processor ID
new processor ID
old pipelineId
new pipelineId
object name
status
API response/error
```

## Single object restore

To restore a single processor:

```text
python3 Get-LMLogAlerts.py \
  --creds-file .sample \
  --create output/sample.json \
  --create-kind processor \
  --create-id 78 \
  --debug
```

The script extracts processor `78`, removes its server-generated `id`, verifies the required fields:

```text
name
alertQuery
alertType
severity
```

and POSTs the object to:

```text
/logpipelines/processors
```

## Why the earlier 400 happened

The earlier command:

```text
python Get-LMLogAlerts.py \
  --creds-file .sample \
  --create output/sample.json \
  --create-kind processor \
  --debug
```

was sending the entire backup document as the POST body.

The backup is structured as:

```text
{
  "logpipelines": [...],
  "processors": [...]
}
```

so the API could not find `name`, `alertQuery`, `alertType`, or `severity` at the POST root.

The new `--create-id` handling extracts one processor from the backup before POSTing.

## HTML report

Generate:

```text
python3 Get-LMLogAlerts.py \
  --creds-file .sample \
  --show-tree \
  --html output/logalerts.html
```

The HTML table uses horizontally resizable header cells so columns can be dragged wider or narrower in the browser.

## Log partition handling

The current LogAlert Group API model includes a `partitions` array on the LogAlert Group object.

The supplied backup does not contain `partitions` on the pipeline objects.

When that property is missing, the restore uses:

```text
--partition default
```

or the partition specified by the user.

Examples:

```text
python3 Get-LMLogAlerts.py --creds-file .sample --restore output/sample.json --partition default --debug
```

Custom partition:

```text
python3 Get-LMLogAlerts.py --creds-file .sample --restore output/sample.json --partition prod-logs-90d --debug
```

LogicMonitor documents `default` as the initial/default log partition.

## LMv1 authentication

POST requests sign the exact request data in this order:

```text
HTTP_VERB + EPOCH + REQUEST_BODY + RESOURCE_PATH
```

GET requests omit the body:

```text
HTTP_VERB + EPOCH + RESOURCE_PATH
```

The authorization header is:

```text
LMv1 ACCESS_ID:SIGNATURE:EPOCH
```

The access key and authorization signature are redacted from debug output.

## Dependencies

```text
pip install requests python-dotenv tabulate
```

Python 3.8+ is recommended.

## No-argument behavior

Running:

```text
python3 Get-LMLogAlerts.py
```

shows the complete help and examples without requiring credentials.

## Discovery / collection scripts

This utility is a standalone REST API utility.

```text
Discovery script changed:  No
Collection script changed: No
```

## References

LogicMonitor REST API v3 Swagger:

https://www.logicmonitor.com/support/rest-api-v3-swagger-documentation

LogicMonitor REST API Change Log:

https://www.logicmonitor.com/support/rest-api-change-log

LogAlert Groups:

https://www.logicmonitor.com/support/lm-logs/logalert-groups

LogAlert:

https://www.logicmonitor.com/support/lm-logs/logalert

## Debug authentication status

With `--debug`, the script now reports authentication separately from request validation.

For HTTP 401:

```text
[DEBUG] Authentication: FAILED
```

For other HTTP responses, including 400 and 403:

```text
[DEBUG] Authentication: SUCCESS (request reached API authorization/validation)
```

LogicMonitor documents 401/1401 as authentication failure and 403/1403 as authentication succeeded but permission denied.
