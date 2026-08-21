# SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import logging
import os
import requests

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

CONTENT_API_METADATA_URL = "https://tourism.api.opendatahub.com/v1/MetaData"
MOBILITY_API_BASE = "https://mobility.api.opendatahub.com/v2"
REPRESENTATION = "flat"

# Always write next to this script file, no matter where it's run from
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "metadata_vs_mobility_comparison.txt")


def fetch_all_metadata_entries() -> list[dict]:
    """Fetches ALL entries from the MetaData catalog (paginated), including
    ApiUrl and DataProvider, so we can later filter for
    'mobility.api.opendatahub.com' and compare against the real providers.
    NOTE: mobility entries store providers in 'DataProvider', not 'Sources'
    (confirmed against a real mobility MetaData entry - 'Sources' is null
    there). 'Sources' is kept here too since it's still used for tourism
    entries in other scripts, but is not used for the mobility comparison
    below."""
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

    log.info("%d MetaData entries loaded in total.", len(entries))
    return entries


def filter_mobility_entries(entries: list[dict]) -> list[dict]:
    """Keeps only entries whose ApiUrl points to the Mobility API."""
    mobility_entries = [
        e for e in entries
        if "mobility.api.opendatahub.com" in (e.get("ApiUrl") or "")
    ]
    log.info("%d of these are mobility entries (ApiUrl contains mobility.api.opendatahub.com).",
             len(mobility_entries))
    return mobility_entries


def extract_stationtype_from_url(api_url: str) -> str:
    """Tries to extract the StationType name from an ApiUrl like
    '.../v2/flat/ParkingStation' (last URL segment, without query params)."""
    if not api_url:
        return ""
    clean = api_url.split("?")[0].rstrip("/")
    return clean.split("/")[-1]


def fetch_real_stationtypes() -> dict:
    """Fetches the real, current StationType list directly from the Mobility
    API. Returns a dict {stationtype_lowercase: {"id": ..., "self.stations": ...}}."""
    url = f"{MOBILITY_API_BASE}/{REPRESENTATION}/"
    resp = requests.get(url, headers={"Accept": "application/json"}, timeout=30)
    resp.raise_for_status()
    stationtypes = resp.json()
    log.info("%d real StationTypes loaded from the Mobility API.", len(stationtypes))
    return {s.get("id", "").lower(): s for s in stationtypes}


def fetch_stationtype_facts(source_url: str) -> dict:
    """Fetches the station list of a StationType and derives the number of
    stations and the involved data providers (sorigin field) from it."""
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

    return {"station_count": len(stations), "data_providers": providers}


def main() -> None:
    metadata_entries = fetch_all_metadata_entries()
    mobility_metadata = filter_mobility_entries(metadata_entries)
    real_stationtypes = fetch_real_stationtypes()

    # Determine the StationType name for each MetaData entry - keep ALL
    # entries per StationType (not just the last one) so duplicates can be
    # detected and reported.
    from collections import defaultdict
    metadata_by_stype_all = defaultdict(list)
    for entry in mobility_metadata:
        stype_guess = extract_stationtype_from_url(entry.get("ApiUrl", ""))
        metadata_by_stype_all[stype_guess.lower()].append(entry)

    # For comparisons below, use the first entry per StationType
    metadata_by_stype = {key: entries[0] for key, entries in metadata_by_stype_all.items()}

    duplicate_entries = {
        key: entries for key, entries in metadata_by_stype_all.items()
        if len(entries) > 1
    }

    metadata_keys = set(metadata_by_stype.keys())
    real_keys = set(real_stationtypes.keys())

    missing_in_metadata = real_keys - metadata_keys       # exists for real, but not in MetaData
    outdated_in_metadata = metadata_keys - real_keys       # in MetaData, but no longer exists for real
    matching = metadata_keys & real_keys

    no_data_stationtypes = []       # StationTypes without any station/data
    provider_mismatches = []        # StationTypes where Sources in MetaData != real providers
    fully_correct = []              # StationTypes checked and found to have no issues

    log.info("Checking data availability and providers for %d matching StationTypes...", len(matching))
    for key in sorted(matching):
        real_meta = real_stationtypes[key]
        source_url = real_meta.get("self.stations", f"{MOBILITY_API_BASE}/{REPRESENTATION}/{real_meta.get('id')}")

        try:
            facts = fetch_stationtype_facts(source_url)
        except requests.HTTPError as exc:
            log.warning("Could not load facts for '%s': %s", real_meta.get("id"), exc)
            continue

        has_issue = False

        if facts["station_count"] == 0:
            no_data_stationtypes.append(real_meta.get("id"))
            has_issue = True

        metadata_entry = metadata_by_stype[key]
        # "DataProvider" from MetaData - may be missing, None, or a list.
        # NOTE: this used to compare against "Sources", which is null on
        # real mobility entries - "DataProvider" is the correct field.
        metadata_providers = metadata_entry.get("DataProvider") or []
        metadata_providers_set = {str(s) for s in metadata_providers}
        real_providers_set = facts["data_providers"]

        if metadata_providers_set != real_providers_set:
            provider_mismatches.append({
                "stationtype": real_meta.get("id"),
                "metadata_sources": sorted(metadata_providers_set),
                "real_providers": sorted(real_providers_set),
            })
            has_issue = True

        if not has_issue:
            fully_correct.append(real_meta.get("id"))

    def section(f, title, count):
        f.write("\n")
        f.write("=" * 70 + "\n")
        f.write(f" {title} ({count})\n")
        f.write("=" * 70 + "\n")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("#" * 70 + "\n")
        f.write("# COMPARISON: MetaData catalog vs. real Mobility API\n")
        f.write("#" * 70 + "\n\n")

        f.write("SUMMARY\n")
        f.write("-" * 70 + "\n")
        f.write(f"{'MetaData mobility entries:':<40}{len(mobility_metadata):>5}\n")
        f.write(f"{'Unique StationTypes in MetaData:':<40}{len(metadata_by_stype_all):>5}\n")
        f.write(f"{'Duplicate StationTypes in MetaData:':<40}{len(duplicate_entries):>5}\n")
        f.write(f"{'Real StationTypes:':<40}{len(real_stationtypes):>5}\n")
        f.write(f"{'Missing in MetaData:':<40}{len(missing_in_metadata):>5}\n")
        f.write(f"{'Outdated/incorrect in MetaData:':<40}{len(outdated_in_metadata):>5}\n")
        f.write(f"{'No data (0 stations):':<40}{len(no_data_stationtypes):>5}\n")
        f.write(f"{'Data provider mismatches:':<40}{len(provider_mismatches):>5}\n")
        f.write(f"{'Fully correct:':<40}{len(fully_correct):>5}\n")

        section(f, "MISSING IN METADATA", len(missing_in_metadata))
        f.write("StationTypes that exist in the real Mobility API but do\n")
        f.write("not appear in the MetaData catalog:\n\n")
        if missing_in_metadata:
            for i, key in enumerate(sorted(missing_in_metadata), 1):
                f.write(f"  {i:>3}. {real_stationtypes[key].get('id')}\n")
        else:
            f.write("  (none)\n")

        section(f, "DUPLICATE ENTRIES IN METADATA", len(duplicate_entries))
        f.write("StationTypes that appear more than once in the MetaData\n")
        f.write("catalog (e.g. multiple entries pointing to the same ApiUrl):\n\n")
        if duplicate_entries:
            for i, (key, entries) in enumerate(sorted(duplicate_entries.items()), 1):
                stype_name = extract_stationtype_from_url(entries[0].get("ApiUrl", "")) or key
                f.write(f"  {i:>3}. {stype_name} ({len(entries)} entries)\n")
                for entry in entries:
                    f.write(f"       - Shortname: {entry.get('Shortname')}, Id: {entry.get('Id')}\n")
        else:
            f.write("  (none)\n")

        section(f, "OUTDATED/INCORRECT IN METADATA", len(outdated_in_metadata))
        f.write("Entries in the MetaData catalog that point to a StationType\n")
        f.write("that no longer exists:\n\n")
        if outdated_in_metadata:
            for i, key in enumerate(sorted(outdated_in_metadata), 1):
                entry = metadata_by_stype[key]
                f.write(f"  {i:>3}. {entry.get('Shortname')}\n")
                f.write(f"       ApiUrl: {entry.get('ApiUrl')}\n")
        else:
            f.write("  (none)\n")

        section(f, "NO DATA", len(no_data_stationtypes))
        f.write("StationTypes that exist but currently have 0 stations:\n\n")
        if no_data_stationtypes:
            for i, stype in enumerate(no_data_stationtypes, 1):
                f.write(f"  {i:>3}. {stype}\n")
        else:
            f.write("  (none)\n")

        section(f, "DATA PROVIDER MISMATCHES", len(provider_mismatches))
        f.write("Sources field in MetaData vs. real providers (sorigin):\n\n")
        if provider_mismatches:
            for i, mismatch in enumerate(provider_mismatches, 1):
                f.write(f"  {i:>3}. {mismatch['stationtype']}\n")
                f.write(f"       MetaData: {', '.join(mismatch['metadata_sources']) or '(empty)'}\n")
                f.write(f"       Real:     {', '.join(mismatch['real_providers']) or '(none found)'}\n")
        else:
            f.write("  (none)\n")

        section(f, "FULLY CORRECT", len(fully_correct))
        f.write("StationTypes with no issues found:\n\n")
        if fully_correct:
            for i, stype in enumerate(fully_correct, 1):
                f.write(f"  {i:>3}. {stype}\n")
        else:
            f.write("  (none)\n")

    log.info("Done - comparison written to %s", OUTPUT_FILE)


if __name__ == "__main__":
    main()