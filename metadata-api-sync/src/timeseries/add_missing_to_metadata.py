# SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import os
import re
import logging
import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

# Always resolve paths next to this script file, no matter where it's run from
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Safety switch - nothing is written while this is True
DRY_RUN = True

CONFIRMATION_PHRASE = "CREATE ENTRIES"

CONTENT_API_METADATA_URL = "https://tourism.api.opendatahub.com/v1/MetaData"
MOBILITY_API_BASE = "https://mobility.api.opendatahub.com/v2"
REPRESENTATION = "flat"

AUTH_BASE = os.getenv("AUTH_BASE")
REALM = os.getenv("REALM")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")


# ---------------------------------------------------------------------------
# Helpers for naming
# ---------------------------------------------------------------------------

def to_readable_name(name: str) -> str:
    """Turns 'BikeParkingBay' into 'Bike Parking Bay'."""
    name = name.replace("_", " ")
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    words = name.split()
    readable_words = [w if w.isupper() and len(w) > 1 else w.capitalize() for w in words]
    return " ".join(readable_words)


def is_hash_like(provider: str) -> bool:
    """Detects provider values that look like random IDs instead of
    real organization names."""
    digit_count = sum(c.isdigit() for c in provider)
    return len(provider) > 20 and digit_count >= 2


# ---------------------------------------------------------------------------
# Fetching data
# ---------------------------------------------------------------------------

def fetch_all_metadata_entries() -> list[dict]:
    """Gets every entry from the MetaData catalog, page by page."""
    entries = []
    pagenumber = 1
    while True:
        params = {
            "fields": ["Id", "Shortname", "ApiUrl", "ApiDescription", "Sources", "DataProvider"],
            "pagenumber": pagenumber,
            "pagesize": 100,
        }
        resp = requests.get(CONTENT_API_METADATA_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("Items", []) if isinstance(data, dict) else data
        entries.extend(items)
        if isinstance(data, dict) and data.get("NextPage"):
            pagenumber += 1
        else:
            break
    return entries


def extract_stationtype_from_url(api_url: str) -> str:
    """Gets the StationType name from a URL like '.../v2/flat/ParkingStation'."""
    if not api_url:
        return ""
    clean = api_url.split("?")[0].rstrip("/")
    return clean.split("/")[-1]


def fetch_real_stationtypes() -> dict:
    """Gets the real, current StationType list from the Mobility API."""
    url = f"{MOBILITY_API_BASE}/{REPRESENTATION}/"
    resp = requests.get(url, headers={"Accept": "application/json"}, timeout=30)
    resp.raise_for_status()
    stationtypes = resp.json()
    return {s.get("id", "").lower(): s for s in stationtypes}


def fetch_stationtype_facts(source_url: str) -> dict:
    """Gets the stations for one StationType and returns the count
    and the list of data providers."""
    resp = requests.get(source_url, headers={"Accept": "application/json"},
                         params={"limit": -1}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    stations = data if isinstance(data, list) else data.get("data", [])
    providers = set()
    for s in stations:
        origin = s.get("sorigin")
        if origin:
            providers.add(str(origin))
    return {"station_count": len(stations), "data_providers": sorted(providers)}


def find_missing_stationtypes() -> list[dict]:
    """Returns the real StationTypes that have no MetaData entry yet."""
    metadata_entries = fetch_all_metadata_entries()
    metadata_stypes = {
        extract_stationtype_from_url(e.get("ApiUrl", "")).lower()
        for e in metadata_entries
        if "mobility.api.opendatahub.com" in (e.get("ApiUrl") or "")
    }
    real_stationtypes = fetch_real_stationtypes()

    missing = [
        real_stationtypes[key] for key in real_stationtypes
        if key not in metadata_stypes
    ]
    return missing


# ---------------------------------------------------------------------------
# Building the proposed entries - one per data provider
# ---------------------------------------------------------------------------

def build_proposed_entries(stationtype_meta: dict) -> list[dict]:
    """Builds one proposed entry per data provider for a missing
    StationType. If a provider name looks like a random hash, the entry
    gets a generic name instead of 'by <provider>'."""
    stype = stationtype_meta.get("id")
    readable_name = to_readable_name(stype)
    source_url = stationtype_meta.get("self.stations", f"{MOBILITY_API_BASE}/{REPRESENTATION}/{stype}")

    try:
        facts = fetch_stationtype_facts(source_url)
    except requests.HTTPError as exc:
        log.warning("Could not load facts for '%s': %s", stype, exc)
        facts = {"station_count": None, "data_providers": []}

    providers = facts["data_providers"]

    if not providers:
        return [{
            "Shortname": readable_name,
            "ApiUrl": source_url,
            "DataProvider": [],
        }]

    entries = []
    for provider in providers:
        if is_hash_like(provider):
            shortname = readable_name
        else:
            shortname = f"{readable_name} by {provider}"
        entries.append({
            "Shortname": shortname,
            "ApiUrl": source_url,
            "DataProvider": [provider],
        })
    return entries


def build_entry_payload(proposed_entry: dict, stype: str) -> dict:
    """Builds the final payload to send to the MetaData API."""
    return {
        "Shortname": proposed_entry["Shortname"],
        "BaseUrl": MOBILITY_API_BASE.rsplit("/v2", 1)[0],
        "PathParam": ["v2", REPRESENTATION, stype],
        "ApiFilter": [],
        "DataProvider": proposed_entry["DataProvider"],
        "Type": None,
        "ApiType": "timeseries",
        "Dataspace": "mobility",
        "ApiDescription": {
            "en": f"Mobility dataset '{proposed_entry['Shortname']}' from Open Data Hub",
        },
    }


# ---------------------------------------------------------------------------
# Writing (only reached after explicit confirmation)
# ---------------------------------------------------------------------------

def get_access_token() -> str:
    """Logs in and returns an access token for the write request."""
    token_url = f"{AUTH_BASE}/auth/realms/{REALM}/protocol/openid-connect/token"
    token_form = {
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }
    resp = requests.post(token_url, data=token_form,
                          headers={"Content-Type": "application/x-www-form-urlencoded"},
                          timeout=30)
    resp.raise_for_status()
    return resp.json()["access_token"]


def create_metadata_entry(payload: dict, access_token: str) -> None:
    """Sends one new entry to the MetaData API."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    resp = requests.post(CONTENT_API_METADATA_URL, json=payload, headers=headers, timeout=30)
    if resp.status_code >= 300:
        log.error("Failed to create entry '%s': %s - %s",
                   payload["Shortname"], resp.status_code, resp.text)
        resp.raise_for_status()
    log.info("Created entry: %s", payload["Shortname"])


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------

def main() -> None:
    log.info("Looking for StationTypes missing from MetaData...")
    missing = find_missing_stationtypes()

    if not missing:
        print("No missing StationTypes found. Nothing to do.")
        return

    all_proposed = {}
    for stationtype_meta in missing:
        stype = stationtype_meta.get("id")
        log.info("Building proposal for '%s'...", stype)
        all_proposed[stype] = build_proposed_entries(stationtype_meta)

    # Show the preview
    print("\n" + "=" * 70)
    print(f" PREVIEW: {len(missing)} StationTypes missing from MetaData")
    print("=" * 70 + "\n")

    total_entries = 0
    for stype, entries in all_proposed.items():
        print(f"{stype} ({len(entries)} entries)")
        for entry in entries:
            print(f"  - Shortname: {entry['Shortname']}")
            print(f"    ApiUrl:    {entry['ApiUrl']}")
            print(f"    Provider:  {entry['DataProvider'] or '(none)'}")
        total_entries += len(entries)
        print()

    print("-" * 70)
    print(f"Total: {len(missing)} StationTypes -> {total_entries} MetaData entries would be created")
    print("-" * 70 + "\n")

    if DRY_RUN:
        print("DRY_RUN is enabled - nothing will be written.")
        print("Set DRY_RUN = False in the script and re-run to actually create entries.")
        return

    # Ask for confirmation before writing anything
    print(f"To proceed, type exactly: {CONFIRMATION_PHRASE}")
    answer = input("> ").strip()
    if answer != CONFIRMATION_PHRASE:
        print("Confirmation phrase did not match. Aborting - nothing was written.")
        return

    # Write the entries
    log.info("Confirmed. Fetching access token...")
    access_token = get_access_token()

    for stype, entries in all_proposed.items():
        for entry in entries:
            payload = build_entry_payload(entry, stype)
            try:
                create_metadata_entry(payload, access_token)
            except requests.HTTPError:
                log.error("Stopping after failure on '%s'.", entry["Shortname"])
                return

    log.info("Done. %d entries created.", total_entries)


if __name__ == "__main__":
    main()