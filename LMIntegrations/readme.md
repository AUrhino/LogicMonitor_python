# LogicMonitor API - Get LM Integrations

This Python script uses the LogicMonitor API to retrieve alert integrations.

It can display integrations in a formatted summary table, show the complete JSON response, or retrieve a specific integration by ID.

---

## LogicMonitor API Credentials

The script requires the following environment variables:

- `ACCESS_ID`
- `ACCESS_KEY`
- `COMPANY`

---

## Setup

1. **Clone or download this repository.**
2. **Create a `.env` file in the project root** with the following content:

```env
ACCESS_ID=your_access_id
ACCESS_KEY=your_access_key
COMPANY=your_company_name
```

3. **Install the required Python packages:**

```bash
pip install requests tabulate python-dotenv
```

---

## API Endpoints

The script uses the following LogicMonitor REST API endpoints:

```text
GET /setting/integrations
GET /setting/integrations/{id}
```

---

## Output

- `--list` displays integrations in a formatted summary table.
- `--list-full` displays the complete JSON response returned by `/setting/integrations`.
- `--id` displays all returned fields for a specific integration in a field/value table.
- `--debug` displays additional API request and response information.

---

## Requirements

- Python 3.8+
- `requests`
- `tabulate`
- `python-dotenv`

---

## Examples

```text
- Show help:
    python3 Get-LMIntegrations.py

- List all integrations in a summary table:
    python3 Get-LMIntegrations.py --list

- Show the complete JSON response for all integrations:
    python3 Get-LMIntegrations.py --list-full

- Get a specific integration by ID:
    python3 Get-LMIntegrations.py --id 12

- Enable debug output when listing integrations:
    python3 Get-LMIntegrations.py --list --debug

- Enable debug output with the full JSON response:
    python3 Get-LMIntegrations.py --list-full --debug

- Enable debug output for a specific integration:
    python3 Get-LMIntegrations.py --id 12 --debug
```

---

## Options

| Option | Description |
|---|---|
| `--list` | List all alert integrations in a summary table. |
| `--list-full` | Show the complete JSON response for all alert integrations. |
| `--id ID` | Retrieve and display a specific alert integration by ID. |
| `--debug` | Enable debug output and display API request information. |

---

## Author

Ryan Gillan  
Email: ryangillan@gmail.com
