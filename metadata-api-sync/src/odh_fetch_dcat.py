import json
import logging
import os
import requests
from rdflib import Graph, Namespace, URIRef, Literal, BNode
from rdflib.namespace import DCAT, DCTERMS, RDF, FOAF, XSD

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

MOBILITY_API_BASE = "https://mobility.api.opendatahub.com/v2"
REPRESENTATION = "flat"
MOBILITY_BEARER_TOKEN = ""

# leer = alle StationTypes werden ausgegeben, keine Einschränkung
STATIONTYPE_FILTER = []

# -1 = kein Limit, wirklich ALLE Stationen eines Typs abrufen statt nur
# der ersten Seite (die API begrenzt sonst standardmäßig, z.B. auf 200)
LIMIT = -1

# Optional: nur Stationen eines bestimmten Datenanbieters abrufen,
# z.B. "A22" - wird als "where"-Filter an die API-URL angehängt.
# Leer lassen ("") = kein Filter, alle Anbieter.
ORIGIN_FILTER = ""

# Pfad relativ zu DIESER Skript-Datei, nicht zum Arbeitsverzeichnis - so
# funktioniert es unabhängig davon, von wo aus das Skript gestartet wird
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DESCRIPTIONS_CONFIG_FILE = os.path.join(SCRIPT_DIR, "stationtype_descriptions.json")

OUTPUT_TXT_FILE = os.path.join(SCRIPT_DIR, "output.txt")
OUTPUT_JSONLD_FILE = os.path.join(SCRIPT_DIR, "output.jsonld")

ODH_HEADERS = {"Accept": "application/json"}
if MOBILITY_BEARER_TOKEN:
    ODH_HEADERS["Authorization"] = f"Bearer {MOBILITY_BEARER_TOKEN}"

# URI für den übergeordneten Catalog - fasst alle Datasets zusammen
CATALOG_URI = URIRef("https://mobility.api.opendatahub.com/v2/catalog")

ODH = Namespace("https://opendatahub.com/ns#")


def load_stationtype_descriptions() -> dict:
    log.info("Suche Beschreibungs-Config unter: %s", DESCRIPTIONS_CONFIG_FILE)
    try:
        with open(DESCRIPTIONS_CONFIG_FILE, "r", encoding="utf-8") as f:
            descriptions = json.load(f)
        log.info("%d Beschreibungen aus Config-Datei geladen.", len(descriptions))
        return descriptions
    except FileNotFoundError:
        log.warning("Config-Datei NICHT gefunden - nutze nur generische Fallback-Texte.")
        return {}
    except json.JSONDecodeError as exc:
        log.warning("Config-Datei ist kein gültiges JSON (%s) - nutze nur Fallback-Texte.", exc)
        return {}


def fetch_odh_stationtypes() -> list[dict]:
    url = f"{MOBILITY_API_BASE}/{REPRESENTATION}/"
    log.info("Rufe ODH StationType-Liste ab: %s", url)
    resp = requests.get(url, headers=ODH_HEADERS, timeout=30)
    resp.raise_for_status()
    stationtypes = resp.json()

    if STATIONTYPE_FILTER:
        stationtypes = [s for s in stationtypes if s.get("id") in STATIONTYPE_FILTER]

    log.info("%d StationTypes werden ausgegeben.", len(stationtypes))
    return stationtypes


def build_query_params() -> dict:
    params = {"limit": LIMIT}
    if ORIGIN_FILTER:
        params["where"] = f'sorigin.eq."{ORIGIN_FILTER}"'
    return params


def fetch_stationtype_facts(source_url: str) -> dict:
    params = build_query_params()
    resp = requests.get(source_url, headers=ODH_HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    stations = data if isinstance(data, list) else data.get("data", [])

    providers = set()
    for s in stations:
        origin = s.get("sorigin")
        if origin:
            providers.add(str(origin))

    return {
        "station_count": len(stations),
        "data_providers": sorted(providers),
    }


def add_stationtype_to_graph(g: Graph, stype: str, description: str, source_url: str,
                              station_count: int | None, data_providers: list[str]) -> None:
    dataset_uri = URIRef(source_url)

    # Verknüpfung mit dem übergeordneten Catalog (DCAT-Pflichtfeld)
    g.add((CATALOG_URI, DCAT.dataset, dataset_uri))

    g.add((dataset_uri, RDF.type, DCAT.Dataset))
    g.add((dataset_uri, DCTERMS.title, Literal(stype)))
    g.add((dataset_uri, DCTERMS.description, Literal(description)))
    g.add((dataset_uri, DCTERMS.identifier, Literal(stype)))

    if station_count is not None:
        g.add((dataset_uri, ODH.stationCount, Literal(station_count, datatype=XSD.integer)))

    for provider in data_providers:
        provider_node = BNode()
        g.add((provider_node, RDF.type, FOAF.Agent))
        g.add((provider_node, FOAF.name, Literal(provider)))
        g.add((dataset_uri, DCTERMS.source, provider_node))

    distribution_uri = URIRef(source_url + "/distribution")
    g.add((distribution_uri, RDF.type, DCAT.Distribution))
    g.add((distribution_uri, DCAT.accessURL, dataset_uri))
    g.add((distribution_uri, DCAT.mediaType, Literal("application/json")))
    g.add((dataset_uri, DCAT.distribution, distribution_uri))


def main() -> None:
    descriptions = load_stationtype_descriptions()
    stationtypes = fetch_odh_stationtypes()

    g = Graph()
    g.bind("dcat", DCAT)
    g.bind("dct", DCTERMS)
    g.bind("foaf", FOAF)
    g.bind("odh", ODH)

    # Pflicht-Ressource laut DCAT-Spezifikation: der Catalog selbst,
    # der alle Datasets über dcat:dataset referenziert
    g.add((CATALOG_URI, RDF.type, DCAT.Catalog))
    g.add((CATALOG_URI, DCTERMS.title, Literal("Open Data Hub Mobility Catalog")))
    g.add((CATALOG_URI, DCTERMS.description, Literal(
        "Catalog of mobility datasets from Open Data Hub, published to the Mobility Data Space"
    )))

    with open(OUTPUT_TXT_FILE, "w", encoding="utf-8") as f:
        f.write(f"Anzahl StationTypes: {len(stationtypes)}\n")
        f.write("=" * 60 + "\n\n")
        for stationtype_meta in stationtypes:
            stype = stationtype_meta.get("id", "unknown")
            source_url = stationtype_meta.get(
                "self.stations", f"{MOBILITY_API_BASE}/{REPRESENTATION}/{stype}"
            )
            try:
                facts = fetch_stationtype_facts(source_url)
            except requests.HTTPError as exc:
                log.warning("Konnte Fakten für '%s' nicht laden: %s", stype, exc)
                facts = {"station_count": None, "data_providers": []}

            description = descriptions.get(
                stype, f"Mobility-Datensatz '{stype}' von Open Data Hub, veröffentlicht im Mobility Data Space",
            )

            f.write(f"ID:            {stype}\n")
            f.write(f"Beschreibung:  {description}\n")
            f.write(f"API-URL:       {source_url}\n")
            f.write(f"Stationen:     {facts['station_count']}\n")
            f.write(f"Datenanbieter: {', '.join(facts['data_providers']) or '-'}\n")
            f.write("-" * 60 + "\n")

            add_stationtype_to_graph(
                g, stype, description, source_url,
                facts["station_count"], facts["data_providers"],
            )

    g.serialize(destination=OUTPUT_JSONLD_FILE, format="json-ld", indent=2)

    log.info("Fertig - Text in %s, DCAT/JSON-LD in %s", OUTPUT_TXT_FILE, OUTPUT_JSONLD_FILE)


if __name__ == "__main__":
    main()