"""
LogicMonitor API - Get Integrations
-----------------------------------
This script retrieves LogicMonitor alert integrations, displays them in an
ASCII table, and retrieves a specific integration by ID.

Requirements:
- Python 3.x
- requests, tabulate, python-dotenv
- .env file with:
ACCESS_ID=your_access_id
ACCESS_KEY=your_access_key
COMPANY=your_company_name

Usage:
- Show help:
    python3 Get-LMIntegrations.py

- List all integrations:
    python3 Get-LMIntegrations.py --list

- Get a specific integration by ID:
    python3 Get-LMIntegrations.py --id 12

- Enable debug output:
    python3 Get-LMIntegrations.py --list --debug
    python3 Get-LMIntegrations.py --id 12 --debug
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import time
from typing import Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv
from tabulate import tabulate


# Load environment variables
load_dotenv()
ACCESS_KEY = os.getenv("ACCESS_KEY")
ACCESS_ID = os.getenv("ACCESS_ID")
COMPANY = os.getenv("COMPANY")

BASE_URL = f"https://{COMPANY}.logicmonitor.com/santaba/rest"
DEBUG = False


def validate_env() -> None:
    """
    Validate required environment variables.
    """
    missing = [
        name
        for name, value in {
            "ACCESS_ID": ACCESS_ID,
            "ACCESS_KEY": ACCESS_KEY,
            "COMPANY": COMPANY,
        }.items()
        if not value
    ]

    if missing:
        print(f"Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)


def debug_print(message: str) -> None:
    """
    Print debug messages when debug mode is enabled.
    """
    if DEBUG:
        print(f"[DEBUG] {message}")


def generate_auth_headers(
    http_verb: str,
    resource_path: str,
    data: str = "",
) -> Dict[str, str]:
    """
    Generate LogicMonitor LMv1 API authentication headers.
    """
    epoch = str(int(time.time() * 1000))
    request_vars = http_verb + epoch + data + resource_path

    hmac_hash = hmac.new(
        ACCESS_KEY.encode(),
        msg=request_vars.encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()

    signature = base64.b64encode(hmac_hash.encode()).decode()
    auth = f"LMv1 {ACCESS_ID}:{signature}:{epoch}"

    return {
        "Content-Type": "application/json",
        "Authorization": auth,
    }


def api_get(resource_path: str) -> Dict:
    """
    Perform a GET request to the LogicMonitor API.
    """
    url = BASE_URL + resource_path
    headers = generate_auth_headers("GET", resource_path)

    debug_print(f"API endpoint: GET {resource_path}")
    debug_print(f"Full URL: {url}")

    try:
        response = requests.get(url, headers=headers, timeout=30)
    except requests.RequestException as exc:
        print(f"Request failed: {exc}")
        return {}

    debug_print(f"Response status: {response.status_code}")

    if response.status_code == 200:
        try:
            payload = response.json()
            debug_print(
                "Response JSON keys: "
                f"{list(payload.keys()) if isinstance(payload, dict) else 'non-dict response'}"
            )
            return payload
        except ValueError:
            print("Error: Response was not valid JSON.")
            return {}

    print(f"Error: {response.status_code} - {response.text}")
    return {}


def display_table(
    data: List[List],
    headers: List[str],
    title: str = "",
) -> None:
    """
    Display data in a formatted ASCII table.
    """
    if title:
        print("\n" + "=" * 70)
        print(title)
        print("=" * 70)

    print(tabulate(data, headers=headers, tablefmt="grid"))


def extract_items_and_total(
    response: Dict,
) -> Tuple[List[Dict], Optional[int]]:
    """
    Support common LogicMonitor top-level and nested pagination formats.
    """
    if not isinstance(response, dict):
        return [], None

    if isinstance(response.get("items"), list):
        return response.get("items", []), response.get("total")

    data = response.get("data", {})
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data.get("items", []), data.get("total")

    return [], None


def get_all_integrations() -> List[Dict]:
    """
    Fetch all alert integrations.
    """
    response = api_get("/setting/integrations")
    items, total = extract_items_and_total(response)

    debug_print(f"Parsed items: {len(items)}")
    debug_print(f"Parsed total: {total}")

    if items:
        items.sort(
            key=lambda integration: (
                integration.get("id") is None,
                integration.get("id"),
            )
        )

    return items


def get_integration_by_id(integration_id: int) -> Dict:
    """
    Fetch a single alert integration by ID.
    """
    response = api_get(f"/setting/integrations/{integration_id}")

    if not isinstance(response, dict):
        print(f"No integration data returned for ID {integration_id}.")
        return {}

    # Direct object response.
    if "id" in response or "name" in response or "type" in response:
        return response

    # Some LogicMonitor endpoints wrap the object in "data".
    data = response.get("data", {})
    if isinstance(data, dict) and data:
        return data

    print(f"No integration data returned for ID {integration_id}.")
    return {}


def format_value(value) -> str:
    """
    Format a value for table display.
    """
    if value is None:
        return ""

    if isinstance(value, (dict, list)):
        return json.dumps(value, indent=2, ensure_ascii=False)

    return str(value)


def build_integration_table_rows(integrations: List[Dict]) -> List[List]:
    """
    Build summary rows for integrations.

    Integration payloads can vary by integration type, so this intentionally
    limits the list view to common fields and leaves --id to show every field.
    """
    rows = []

    for integration in integrations:
        if not isinstance(integration, dict):
            continue

        integration_type = (
            integration.get("type")
            or integration.get("integrationType")
            or integration.get("integration_type")
            or ""
        )

        description = (
            integration.get("description")
            or integration.get("note")
            or ""
        )

        rows.append(
            [
                integration.get("id"),
                integration.get("name"),
                integration_type,
                description,
            ]
        )

    return rows


def list_integrations() -> None:
    """
    Fetch and display all alert integrations.
    """
    print("\nFetching integrations...")
    integrations = get_all_integrations()

    if not integrations:
        print("No integrations found.")
        return

    rows = build_integration_table_rows(integrations)
    headers = ["ID", "Name", "Type", "Description"]

    display_table(rows, headers, "LogicMonitor Integrations")


def show_integration_by_id(integration_id: int) -> None:
    """
    Fetch and display one integration by ID with all returned fields.
    """
    print(f"\nFetching integration ID: {integration_id}")
    integration = get_integration_by_id(integration_id)

    if not integration:
        return

    rows = [
        [key, format_value(integration.get(key))]
        for key in sorted(integration.keys())
    ]

    display_table(
        rows,
        ["Field", "Value"],
        f"LogicMonitor Integration {integration_id}",
    )


def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Retrieve LogicMonitor alert integrations via the "
            "LogicMonitor REST API."
        )
    )

    group = parser.add_mutually_exclusive_group(required=False)

    group.add_argument(
        "--list",
        action="store_true",
        help="List all alert integrations.",
    )

    group.add_argument(
        "--id",
        type=int,
        help="Retrieve a specific alert integration by ID.",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug output and print API endpoints being called.",
    )

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()

    if not (args.list or args.id is not None):
        parser.print_help()
        sys.exit(0)

    return args


if __name__ == "__main__":
    args = parse_args()
    DEBUG = args.debug

    validate_env()

    if args.list:
        list_integrations()
    elif args.id is not None:
        show_integration_by_id(args.id)

# eof
