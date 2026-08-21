# SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import logging
import os
import requests
from rdflib import Graph, Namespace, URIRef, Literal, BNode
from rdflib.namespace import DCAT, DCTERMS, RDF, FOAF

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

CONTENT_API_METADATA_URL = "https://tourism.api.opendatahub.com/v1/MetaData"

# Always write next to this script file, no matter where it's run from
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_JSONLD_FILE = os.path.join(SCRIPT_DIR, "metadata_dcat.jsonld")

CATALOG_URI = URIRef("https://mobility.api.opendatahub.com/v2/catalog")

ODH = Namespace("https://opendatahub.com/ns#")


def fetch_all_metadata_entries() -> list[dict]:
    """Gets every entry from the MetaData catalog, page by page."""
    entries = []
    pagenumber = 1
    while True:
        params = {
            "fields": ["Id", "Shortname", "ApiUrl", "ApiDescription",
                       "DataProvider", "LicenseInfo"],
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
    log.info("%d of these are mobility entries.", len(mobility_entries))
    return mobility_entries


def get_description(entry: dict) -> str:
    """ApiDescription is a language dict, e.g. {"en": "...", "de": "..."}.
    Prefers English, falls back to whatever language is available."""
    descriptions = entry.get("ApiDescription") or {}
    if descriptions.get("en"):
        return descriptions["en"]
    for text in descriptions.values():
        if text:
            return text
    return f"Mobility dataset '{entry.get('Shortname')}' from Open Data Hub"


def add_entry_to_graph(g: Graph, entry: dict) -> None:
    """Adds one MetaData entry to the graph as a dcat:Dataset."""
    api_url = entry.get("ApiUrl")
    if not api_url:
        return

    dataset_uri = URIRef(api_url)

    g.add((CATALOG_URI, DCAT.dataset, dataset_uri))

    g.add((dataset_uri, RDF.type, DCAT.Dataset))
    g.add((dataset_uri, DCTERMS.title, Literal(entry.get("Shortname") or "")))
    g.add((dataset_uri, DCTERMS.description, Literal(get_description(entry))))
    g.add((dataset_uri, DCTERMS.identifier, Literal(entry.get("Id") or "")))

    license_info = entry.get("LicenseInfo") or {}
    if license_info.get("License"):
        g.add((dataset_uri, DCTERMS.license, Literal(license_info["License"])))
    if license_info.get("LicenseHolder"):
        g.add((dataset_uri, DCTERMS.rightsHolder, Literal(license_info["LicenseHolder"])))

    for provider in entry.get("DataProvider") or []:
        provider_node = BNode()
        g.add((provider_node, RDF.type, FOAF.Agent))
        g.add((provider_node, FOAF.name, Literal(provider)))
        g.add((dataset_uri, DCTERMS.source, provider_node))

    distribution_uri = URIRef(api_url + "/distribution")
    g.add((distribution_uri, RDF.type, DCAT.Distribution))
    g.add((distribution_uri, DCAT.accessURL, dataset_uri))
    g.add((distribution_uri, DCAT.mediaType, Literal("application/json")))
    g.add((dataset_uri, DCAT.distribution, distribution_uri))


def main() -> None:
    entries = fetch_all_metadata_entries()
    mobility_entries = entries

    g = Graph()
    g.bind("dcat", DCAT)
    g.bind("dct", DCTERMS)
    g.bind("foaf", FOAF)
    g.bind("odh", ODH)

    g.add((CATALOG_URI, RDF.type, DCAT.Catalog))
    g.add((CATALOG_URI, DCTERMS.title, Literal("Open Data Hub Mobility Catalog")))
    g.add((CATALOG_URI, DCTERMS.description, Literal(
        "Catalog of mobility datasets from the Open Data Hub MetaData API"
    )))

    for entry in mobility_entries:
        add_entry_to_graph(g, entry)

    g.serialize(destination=OUTPUT_JSONLD_FILE, format="json-ld", indent=2)
    log.info("Done - DCAT/JSON-LD written to %s", OUTPUT_JSONLD_FILE)


if __name__ == "__main__":
    main()