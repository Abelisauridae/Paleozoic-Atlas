#!/usr/bin/env python3

from __future__ import annotations

import csv
import json
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

WINDOW_START_MA = 541.0
WINDOW_END_MA = 251.9
PBDB_INTERVAL = "Cambrian,Permian"
PBDB_TAXA_URL = (
    "https://paleobiodb.org/data1.2/taxa/list.csv"
    "?base_name=Animalia&rank=species&show=app,parent,size,class"
    f"&interval={PBDB_INTERVAL}&limit=all"
)
PBDB_OCCS_URL = (
    "https://paleobiodb.org/data1.2/occs/list.csv"
    "?base_name=Animalia&taxon_reso=species&show=coords,class,time"
    f"&interval={PBDB_INTERVAL}&limit=all"
)
WORLD_LAND_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
    "ne_110m_land.geojson"
)
MAX_RECORDS_PER_CHUNK = 2500
MAX_CHUNK_BYTES = 24 * 1024 * 1024
MISSING_TAXA = {
    "",
    "NO_CLASS_SPECIFIED",
    "NO_ORDER_SPECIFIED",
    "NO_FAMILY_SPECIFIED",
    "NO_GENUS_SPECIFIED",
}
PALEOZOIC_PERIODS = [
    ("Cambrian", 541.0, 485.4),
    ("Ordovician", 485.4, 443.8),
    ("Silurian", 443.8, 419.2),
    ("Devonian", 419.2, 358.9),
    ("Carboniferous", 358.9, 298.9),
    ("Permian", 298.9, 251.9),
]
JAWLESS_VERTEBRATE_CLASSES = {
    "agnatha",
    "cephalaspidomorphi",
    "conodonta",
    "ostracodermi",
    "thelodonti",
}
FISH_CLASSES = {
    "acanthodii",
    "actinopterygii",
    "chondrichthyes",
    "osteichthyes",
    "placodermi",
    "sarcopterygii",
}
AMPHIBIAN_CLASSES = {
    "amphibia",
    "lepospondyli",
    "temnospondyli",
}
TETRAPOD_CLASSES = {
    "diapsida",
    "parareptilia",
    "reptilia",
    "synapsida",
    "therapsida",
}
CHELICERATE_CLASSES = {
    "arachnida",
    "eurypterida",
    "merostomata",
    "pycnogonida",
    "xiphosura",
}
CRUSTACEAN_CLASSES = {
    "branchiopoda",
    "cephalocarida",
    "malacostraca",
    "maxillopoda",
    "ostracoda",
    "remipedia",
    "thecostraca",
}
CORAL_CLASSES = {
    "anthozoa",
    "hydrozoa",
    "rugosa",
    "scyphozoa",
    "tabulata",
}
CEPHALOPOD_CLASSES = {
    "ammonoidea",
    "bactritoidea",
    "cephalopoda",
    "nautiloidea",
}


def fetch_file(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["curl", "-Lsf", "-o", str(destination), url],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to fetch {url}: {result.stderr.strip()}")


def ensure_source_file(cache_path: Path, url: str) -> Path:
    if not cache_path.exists():
        fetch_file(url, cache_path)
    return cache_path


def iter_csv_rows(path: Path):
    with path.open(encoding="utf-8", newline="") as handle:
        yield from csv.DictReader(handle)


def parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def clean_taxon(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if cleaned in MISSING_TAXA:
        return None
    return cleaned or None


def clean_interval(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def round_if_number(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def clamp_ma(value: float | None) -> float | None:
    if value is None:
        return None
    return min(max(value, WINDOW_END_MA), WINDOW_START_MA)


def overlaps_target_window(max_ma: float | None, min_ma: float | None) -> bool:
    if max_ma is None:
        return False
    younger = min_ma if min_ma is not None else max_ma
    return max_ma >= WINDOW_END_MA and younger <= WINDOW_START_MA


def overlaps_period(
    older_ma: float | None, younger_ma: float | None, period_start: float, period_end: float
) -> bool:
    if older_ma is None:
        return False
    younger = younger_ma if younger_ma is not None else older_ma
    return older_ma >= period_end and younger <= period_start


def paleozoic_periods_for_range(start_ma: float | None, end_ma: float | None) -> list[str]:
    return [
        name
        for name, period_start, period_end in PALEOZOIC_PERIODS
        if overlaps_period(start_ma, end_ma, period_start, period_end)
    ]


def paleozoic_period_label(start_ma: float | None, end_ma: float | None) -> str | None:
    periods = paleozoic_periods_for_range(start_ma, end_ma)
    if not periods:
        return None
    if len(periods) == 1:
        return periods[0]
    return f"{periods[0]} to {periods[-1]}"


def is_species_name(value: str | None) -> bool:
    return bool(value and value.count(" ") >= 1)


def row_priority(row: dict[str, str]) -> tuple[int, int, int]:
    exact_name = 1 if row.get("taxon_name") == row.get("accepted_name") else 0
    no_difference = 1 if not (row.get("difference") or "").strip() else 0
    occurrences = int(row.get("n_occs") or "0")
    return (exact_name, no_difference, occurrences)


def format_temporal_label(early: str | None, late: str | None) -> str | None:
    if early and late and early != late:
        return f"{early} to {late}"
    return early or late


def pluralize(count: int, singular: str, plural: str | None = None) -> str:
    if count == 1:
        return singular
    return plural or f"{singular}s"


def fauna_group(
    phylum: str | None,
    class_name: str | None,
    order: str | None,
    family: str | None,
) -> str:
    lowered_phylum = (phylum or "").lower()
    lowered_class = (class_name or "").lower()
    lowered_order = (order or "").lower()
    lowered_family = (family or "").lower()

    if lowered_class == "trilobita":
        return "Trilobites"
    if lowered_class in {"insecta", "pterygota"}:
        return "Insects"
    if lowered_class in CHELICERATE_CLASSES or lowered_order in {"eurypterida", "xiphosurida"}:
        return "Chelicerates"
    if lowered_class in CRUSTACEAN_CLASSES:
        return "Crustaceans"
    if lowered_phylum == "arthropoda":
        return "Other arthropods"

    if lowered_phylum == "brachiopoda":
        return "Brachiopods"

    if (
        lowered_class in CEPHALOPOD_CLASSES
        or lowered_order in {"ammonoidea", "orthocerida", "nautilida"}
        or lowered_family in {"orthoceratidae", "goniatitidae"}
    ):
        return "Cephalopods"
    if lowered_class in {"bivalvia", "pelecypoda"}:
        return "Bivalves"
    if lowered_class == "gastropoda":
        return "Gastropods"
    if lowered_phylum == "mollusca":
        return "Other molluscs"

    if lowered_phylum in {"bryozoa", "ectoprocta"}:
        return "Bryozoans"
    if lowered_phylum == "porifera":
        return "Sponges"
    if lowered_phylum == "echinodermata":
        return "Echinoderms"
    if lowered_phylum == "annelida":
        return "Annelids"
    if lowered_phylum == "hemichordata":
        return "Graptolites and kin"
    if lowered_class in CORAL_CLASSES or lowered_phylum == "cnidaria":
        return "Corals and cnidarians"

    if lowered_phylum == "chordata":
        if lowered_class in JAWLESS_VERTEBRATE_CLASSES:
            return "Jawless vertebrates"
        if lowered_class in FISH_CLASSES:
            return "Fishes"
        if lowered_class in AMPHIBIAN_CLASSES or lowered_order in AMPHIBIAN_CLASSES:
            return "Amphibians"
        if lowered_class in TETRAPOD_CLASSES or lowered_order in TETRAPOD_CLASSES:
            return "Tetrapods"
        return "Other chordates"

    return "Other animals"


def fauna_noun(group: str) -> str:
    return {
        "Amphibians": "amphibian",
        "Annelids": "annelid",
        "Bivalves": "bivalve",
        "Brachiopods": "brachiopod",
        "Bryozoans": "bryozoan",
        "Cephalopods": "cephalopod",
        "Chelicerates": "chelicerate",
        "Corals and cnidarians": "cnidarian",
        "Crustaceans": "crustacean",
        "Echinoderms": "echinoderm",
        "Fishes": "fish",
        "Gastropods": "gastropod",
        "Graptolites and kin": "hemichordate",
        "Insects": "insect",
        "Jawless vertebrates": "jawless vertebrate",
        "Other animals": "animal",
        "Other arthropods": "arthropod",
        "Other chordates": "chordate",
        "Other molluscs": "mollusc",
        "Sponges": "sponge",
        "Tetrapods": "tetrapod",
        "Trilobites": "trilobite",
    }.get(group, "animal")


def build_time_phrase(temporal_range: dict) -> str:
    label = temporal_range.get("label")
    period = temporal_range.get("period")
    if label and period and label != period:
        return f"from the {label} interval span of the {period}"
    if label:
        return f"from the {label}"
    if period:
        return f"from the {period}"
    return "from the Paleozoic"


def build_species_description(species: dict) -> dict:
    noun = fauna_noun(species["faunaGroup"])
    opening = (
        f"{species['scientificName']} was a Paleozoic {noun} "
        f"{build_time_phrase(species['temporalRange'])}."
    )
    if species["localityCount"] > 0:
        locality_sentence = (
            f"It is currently linked to {species['localityCount']} mapped fossil "
            f"{pluralize(species['localityCount'], 'locality', 'localities')} "
            f"in the atlas."
        )
    else:
        locality_sentence = (
            "No mapped fossil locality is currently attached to this species "
            "in the generated atlas."
        )
    return {"summary": f"{opening} {locality_sentence}"}


def round_geometry_coordinates(coords):
    if isinstance(coords, list):
        if coords and isinstance(coords[0], (int, float)):
            return [round(float(coords[0]), 3), round(float(coords[1]), 3)]
        return [round_geometry_coordinates(item) for item in coords]
    return coords


def simplify_land_geojson(raw_geojson: dict) -> dict:
    features = []
    for feature in raw_geojson.get("features", []):
        geometry = feature.get("geometry") or {}
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": geometry.get("type"),
                    "coordinates": round_geometry_coordinates(
                        geometry.get("coordinates", [])
                    ),
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def taxonomy_path(species: dict) -> list[str]:
    values = [
        species.get("phylum"),
        species.get("className"),
        species.get("order"),
        species.get("family"),
        species.get("genus"),
    ]
    return [value for value in values if value]


def merge_taxonomy_value(existing: str | None, new_value: str | None) -> str | None:
    return existing or new_value


def make_species_record(
    species_id: str,
    scientific_name: str,
    phylum: str | None,
    class_name: str | None,
    order: str | None,
    family: str | None,
    genus: str | None,
    start_ma: float | None,
    end_ma: float | None,
    early_interval: str | None,
    late_interval: str | None,
    total_occurrences: int = 0,
) -> dict:
    period_label = paleozoic_period_label(start_ma, end_ma)
    temporal_range = {
        "era": "Paleozoic",
        "period": period_label,
        "periods": paleozoic_periods_for_range(start_ma, end_ma),
        "label": format_temporal_label(early_interval, late_interval),
        "earlyInterval": early_interval,
        "lateInterval": late_interval,
        "startMa": round_if_number(start_ma),
        "endMa": round_if_number(end_ma),
    }
    species = {
        "id": int(species_id),
        "scientificName": scientific_name,
        "genus": genus,
        "family": family,
        "order": order,
        "className": class_name,
        "phylum": phylum,
        "faunaGroup": fauna_group(phylum, class_name, order, family),
        "taxonomyPath": [],
        "temporalRange": temporal_range,
        "pbdb": {
            "acceptedNo": int(species_id),
            "occurrenceCount": total_occurrences,
            "isExtant": False,
        },
        "description": None,
        "localityCount": 0,
        "localities": [],
        "coordinateBounds": None,
    }
    species["taxonomyPath"] = taxonomy_path(species)
    species["description"] = build_species_description(species)
    return species


def build_database(taxa_path: Path, occurrences_path: Path) -> dict:
    extant_species_ids: set[str] = set()
    preferred_taxa: dict[str, dict[str, str]] = {}
    total_taxa_occurrences: dict[str, int] = {}

    for row in iter_csv_rows(taxa_path):
        key = row.get("accepted_no") or row.get("taxon_no")
        if row.get("accepted_rank") == "species" and row.get("is_extant") == "extant" and key:
            extant_species_ids.add(key)

    for row in iter_csv_rows(taxa_path):
        if row.get("accepted_rank") != "species":
            continue
        if row.get("is_extant") == "extant":
            continue
        flags = row.get("flags", "")
        if "F" in flags or "I" in flags:
            continue
        accepted_name = row.get("accepted_name") or row.get("taxon_name")
        if not is_species_name(accepted_name):
            continue
        key = row.get("accepted_no") or row.get("taxon_no")
        if not key or key in extant_species_ids:
            continue

        start_ma = parse_float(row.get("firstapp_max_ma"))
        younger_limit = parse_float(row.get("lastapp_min_ma"))
        if younger_limit is None:
            younger_limit = parse_float(row.get("lastapp_max_ma"))
        if not overlaps_target_window(start_ma, younger_limit):
            continue

        existing = preferred_taxa.get(key)
        if existing is None or row_priority(row) > row_priority(existing):
            preferred_taxa[key] = row
        total_taxa_occurrences[key] = int(row.get("n_occs") or "0")

    species_by_id: dict[str, dict] = {}
    locality_map: defaultdict[str, dict[str, dict]] = defaultdict(dict)
    filtered_occurrence_counts: Counter[str] = Counter()
    occurrence_start_bounds: defaultdict[str, list[float]] = defaultdict(list)
    occurrence_end_bounds: defaultdict[str, list[float]] = defaultdict(list)

    for key, row in preferred_taxa.items():
        scientific_name = row.get("accepted_name") or row.get("taxon_name") or ""
        genus = clean_taxon(row.get("genus")) or scientific_name.split()[0]
        family = clean_taxon(row.get("family"))
        order = clean_taxon(row.get("order"))
        class_name = clean_taxon(row.get("class"))
        phylum = clean_taxon(row.get("phylum"))
        early_interval = clean_interval(row.get("early_interval"))
        late_interval = clean_interval(row.get("late_interval"))
        start_ma = clamp_ma(parse_float(row.get("firstapp_max_ma")))
        end_source = parse_float(row.get("lastapp_min_ma"))
        if end_source is None:
            end_source = parse_float(row.get("lastapp_max_ma"))
        end_ma = clamp_ma(end_source)
        species_by_id[key] = make_species_record(
            key,
            scientific_name,
            phylum,
            class_name,
            order,
            family,
            genus,
            start_ma,
            end_ma,
            early_interval,
            late_interval,
            total_taxa_occurrences.get(key, 0),
        )

    for row in iter_csv_rows(occurrences_path):
        if row.get("accepted_rank") != "species":
            continue
        flags = row.get("flags", "")
        if "F" in flags or "I" in flags:
            continue
        key = row.get("accepted_no")
        if not key or key in extant_species_ids:
            continue

        scientific_name = row.get("accepted_name") or row.get("identified_name") or ""
        if not is_species_name(scientific_name):
            continue

        max_ma = parse_float(row.get("max_ma"))
        min_ma = parse_float(row.get("min_ma"))
        if not overlaps_target_window(max_ma, min_ma):
            continue

        filtered_occurrence_counts[key] += 1
        if max_ma is not None:
            occurrence_start_bounds[key].append(clamp_ma(max_ma))
        if min_ma is not None:
            occurrence_end_bounds[key].append(clamp_ma(min_ma))

        lat = parse_float(row.get("lat"))
        lng = parse_float(row.get("lng"))
        if lat is None or lng is None:
            continue

        if key not in species_by_id:
            genus = clean_taxon(row.get("genus")) or scientific_name.split()[0]
            species_by_id[key] = make_species_record(
                key,
                scientific_name,
                clean_taxon(row.get("phylum")),
                clean_taxon(row.get("class")),
                clean_taxon(row.get("order")),
                clean_taxon(row.get("family")),
                genus,
                clamp_ma(max_ma),
                clamp_ma(min_ma),
                clean_interval(row.get("early_interval")),
                clean_interval(row.get("late_interval")),
                0,
            )
        else:
            species = species_by_id[key]
            species["phylum"] = merge_taxonomy_value(
                species.get("phylum"), clean_taxon(row.get("phylum"))
            )
            species["className"] = merge_taxonomy_value(
                species.get("className"), clean_taxon(row.get("class"))
            )
            species["order"] = merge_taxonomy_value(
                species.get("order"), clean_taxon(row.get("order"))
            )
            species["family"] = merge_taxonomy_value(
                species.get("family"), clean_taxon(row.get("family"))
            )
            species["genus"] = merge_taxonomy_value(
                species.get("genus"), clean_taxon(row.get("genus"))
            )
            species["faunaGroup"] = fauna_group(
                species.get("phylum"),
                species.get("className"),
                species.get("order"),
                species.get("family"),
            )
            species["taxonomyPath"] = taxonomy_path(species)

        locality_key = row.get("collection_no") or (
            f"{round(lat, 3)}:{round(lng, 3)}:{row.get('early_interval')}:{row.get('late_interval')}"
        )
        locality = locality_map[key].setdefault(
            locality_key,
            {
                "collectionNo": int(row["collection_no"]) if row.get("collection_no") else None,
                "lat": round(lat, 4),
                "lng": round(lng, 4),
                "earlyInterval": clean_interval(row.get("early_interval")),
                "lateInterval": clean_interval(row.get("late_interval")),
                "startMa": round_if_number(clamp_ma(max_ma)),
                "endMa": round_if_number(clamp_ma(min_ma)),
                "count": 0,
            },
        )
        locality["count"] += 1

    for key, species in species_by_id.items():
        if occurrence_start_bounds.get(key):
            start_candidates = [species["temporalRange"].get("startMa")] + occurrence_start_bounds[key]
            start_values = [value for value in start_candidates if value is not None]
            if start_values:
                species["temporalRange"]["startMa"] = round_if_number(max(start_values))
        if occurrence_end_bounds.get(key):
            end_candidates = [species["temporalRange"].get("endMa")] + occurrence_end_bounds[key]
            end_values = [value for value in end_candidates if value is not None]
            if end_values:
                species["temporalRange"]["endMa"] = round_if_number(min(end_values))

        species["temporalRange"]["periods"] = paleozoic_periods_for_range(
            species["temporalRange"].get("startMa"),
            species["temporalRange"].get("endMa"),
        )
        species["temporalRange"]["period"] = paleozoic_period_label(
            species["temporalRange"].get("startMa"),
            species["temporalRange"].get("endMa"),
        )

        localities = sorted(
            locality_map.get(key, {}).values(),
            key=lambda item: (-item["count"], item["lat"], item["lng"]),
        )
        species["localities"] = localities
        species["localityCount"] = len(localities)
        species["pbdb"]["occurrenceCount"] = filtered_occurrence_counts.get(
            key,
            species["pbdb"]["occurrenceCount"],
        )
        if localities:
            lats = [item["lat"] for item in localities]
            lngs = [item["lng"] for item in localities]
            species["coordinateBounds"] = {
                "minLat": min(lats),
                "maxLat": max(lats),
                "minLng": min(lngs),
                "maxLng": max(lngs),
            }
        species["faunaGroup"] = fauna_group(
            species.get("phylum"),
            species.get("className"),
            species.get("order"),
            species.get("family"),
        )
        species["taxonomyPath"] = taxonomy_path(species)
        species["description"] = build_species_description(species)

    species_list = sorted(species_by_id.values(), key=lambda item: item["scientificName"])
    fauna_counts = Counter(species["faunaGroup"] for species in species_list)
    phylum_counts = Counter(species["phylum"] or "Unclassified" for species in species_list)
    class_counts = Counter(species["className"] or "Unclassified" for species in species_list)
    period_counts = Counter(
        period for species in species_list for period in species["temporalRange"].get("periods", [])
    )
    mapped_species = sum(1 for species in species_list if species["localityCount"] > 0)
    locality_count = sum(species["localityCount"] for species in species_list)
    occurrence_count = sum(species["pbdb"]["occurrenceCount"] for species in species_list)

    return {
        "metadata": {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "datasetName": "Paleozoic Fauna Atlas",
            "scope": {
                "baseName": "Animalia",
                "timeWindow": {
                    "startMa": WINDOW_START_MA,
                    "endMa": WINDOW_END_MA,
                    "intervalQuery": PBDB_INTERVAL,
                },
                "periods": [name for name, _, _ in PALEOZOIC_PERIODS],
            },
            "speciesCount": len(species_list),
            "mappedSpeciesCount": mapped_species,
            "localityCount": locality_count,
            "occurrenceCount": occurrence_count,
            "faunaGroupCounts": dict(sorted(fauna_counts.items())),
            "phylumCounts": dict(sorted(phylum_counts.items())),
            "classCounts": dict(sorted(class_counts.items())),
            "periodCounts": dict(period_counts),
            "notes": [
                "Species are sourced from the PBDB Animalia taxonomy feed filtered to the Cambrian through Permian query window.",
                "The working scope is Paleozoic animal fauna across major invertebrate and chordate groups, including trilobites, brachiopods, molluscs, echinoderms, corals, sponges, fishes, amphibians, and early tetrapods.",
                "Extant species are excluded using the PBDB is_extant flag from the taxonomic feed.",
                "Form taxa and ichnotaxa are excluded by removing PBDB records flagged with F and/or I.",
                "A local numeric age filter retains records that overlap 541.0 Ma to 251.9 Ma, covering the Cambrian through Permian.",
                "Displayed temporal ranges are clamped to the target Paleozoic window when a taxon range crosses the 541.0 Ma or 251.9 Ma boundary.",
                "Map localities are aggregated from PBDB species-level fossil occurrences with coordinates.",
            ],
            "sources": [
                {
                    "name": "Paleobiology Database taxonomic names API",
                    "url": PBDB_TAXA_URL,
                    "role": "Accepted Paleozoic animal species, taxonomy, and broad temporal ranges",
                },
                {
                    "name": "Paleobiology Database fossil occurrences API",
                    "url": PBDB_OCCS_URL,
                    "role": "Occurrence coordinates and interval data",
                },
                {
                    "name": "Natural Earth land polygons",
                    "url": WORLD_LAND_URL,
                    "role": "Simplified world land backdrop for atlas views",
                },
            ],
        },
        "species": species_list,
    }


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")


def write_js_assignment(path: Path, variable_name: str, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"window.{variable_name} = {json.dumps(payload, separators=(',', ':'))};\n",
        encoding="utf-8",
    )


def finalize_chunk(
    chunk_index: int,
    records: list[dict],
    manifests: list[dict],
    chunks: list[dict],
    approx_bytes: int,
) -> None:
    file_name = f"paleozoic-fauna-species-{chunk_index:03d}.json"
    payload = {
        "chunkIndex": chunk_index,
        "species": records,
    }
    manifests.append(
        {
            "chunkIndex": chunk_index,
            "file": f"chunks/{file_name}",
            "speciesCount": len(records),
            "firstSpecies": records[0]["scientificName"],
            "lastSpecies": records[-1]["scientificName"],
            "approxBytes": approx_bytes,
        }
    )
    chunks.append(payload)


def chunk_payload_base_size(chunk_index: int) -> int:
    return len(f'{{"chunkIndex":{chunk_index},"species":[]}}'.encode("utf-8"))


def species_record_size(species: dict) -> int:
    return len(json.dumps(species, separators=(",", ":")).encode("utf-8"))


def build_chunk_manifest(species_list: list[dict]) -> tuple[list[dict], list[dict]]:
    manifests: list[dict] = []
    chunks: list[dict] = []
    chunk_index = 1
    records: list[dict] = []
    current_size = chunk_payload_base_size(chunk_index)

    for species in species_list:
        record_size = species_record_size(species)
        single_record_size = chunk_payload_base_size(chunk_index) + record_size
        if single_record_size > MAX_CHUNK_BYTES:
            raise RuntimeError(
                f"Single species record exceeds the per-file size limit: {species['scientificName']}"
            )

        added_bytes = record_size + (1 if records else 0)
        exceeds_record_cap = len(records) + 1 > MAX_RECORDS_PER_CHUNK
        exceeds_byte_cap = current_size + added_bytes > MAX_CHUNK_BYTES

        if records and (exceeds_record_cap or exceeds_byte_cap):
            finalize_chunk(chunk_index, records, manifests, chunks, current_size)
            chunk_index += 1
            records = [species]
            current_size = chunk_payload_base_size(chunk_index) + record_size
            continue

        records.append(species)
        current_size += added_bytes

    if records:
        finalize_chunk(chunk_index, records, manifests, chunks, current_size)

    return manifests, chunks


def write_chunked_database(data_dir: Path, database: dict) -> dict:
    species_list = database["species"]
    manifests, chunks = build_chunk_manifest(species_list)

    index_payload = {
        "format": "chunked-v1",
        "metadata": {
            **database["metadata"],
            "chunkCount": len(chunks),
            "chunkMaxRecords": MAX_RECORDS_PER_CHUNK,
            "chunkMaxBytes": MAX_CHUNK_BYTES,
        },
        "chunks": manifests,
    }

    write_json(data_dir / "paleozoic-fauna-atlas.json", index_payload)
    write_js_assignment(
        data_dir / "paleozoic-fauna-atlas.js",
        "PALEOZOIC_FAUNA_DATA",
        index_payload,
    )

    chunks_dir = data_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    for existing_chunk in chunks_dir.glob("*.json"):
        existing_chunk.unlink()

    for chunk in chunks:
        write_json(
            chunks_dir / f"paleozoic-fauna-species-{chunk['chunkIndex']:03d}.json",
            chunk,
        )

    return index_payload


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    data_dir = project_root / "data"
    raw_dir = data_dir / "raw"

    taxa_path = ensure_source_file(
        raw_dir / "pbdb-paleozoic-animal-taxa.csv",
        PBDB_TAXA_URL,
    )
    occurrences_path = ensure_source_file(
        raw_dir / "pbdb-paleozoic-animal-occurrences.csv",
        PBDB_OCCS_URL,
    )
    world_land_path = ensure_source_file(raw_dir / "world-land.geojson", WORLD_LAND_URL)
    land_geojson = simplify_land_geojson(json.loads(world_land_path.read_text(encoding="utf-8")))

    database = build_database(taxa_path, occurrences_path)

    index_payload = write_chunked_database(data_dir, database)
    write_json(data_dir / "world-land.json", land_geojson)
    write_js_assignment(data_dir / "world-land.js", "PALEOZOIC_FAUNA_WORLD", land_geojson)

    metadata = database["metadata"]
    print(f"Species: {metadata['speciesCount']}")
    print(f"Mapped species: {metadata['mappedSpeciesCount']}")
    print(f"Localities: {metadata['localityCount']}")
    print(f"Occurrences: {metadata['occurrenceCount']}")
    print(f"Chunks: {index_payload['metadata']['chunkCount']}")


if __name__ == "__main__":
    main()
