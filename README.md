# Paleozoic Fauna Atlas

Interactive static atlas of Paleozoic animal species built from Paleobiology Database records.

This atlas covers fauna from the Cambrian through the Permian and intentionally includes major Paleozoic animal groups rather than only vertebrates. The current pass spans trilobites and other arthropods, brachiopods, molluscs, bryozoans, corals, echinoderms, sponges, fishes, amphibians, and early tetrapods.

## Open the atlas

Open `index.html` or publish the folder with GitHub Pages to use the interactive atlas UI.

## Current dataset coverage

- 47,805 Paleozoic animal species
- 47,771 species with mapped fossil coordinates
- 245,778 aggregated localities
- 249,393 filtered PBDB occurrences
- 20 chunk files, with the largest generated chunk around 4.2 MB

## Scope

- Source taxon: `Animalia`
- Time window: `541.0 Ma` to `251.9 Ma`
- Period coverage: Cambrian, Ordovician, Silurian, Devonian, Carboniferous, and Permian
- Coverage goal: accepted species-level fossil animal taxa that overlap the target window
- Exclusions: extant species, form taxa, and ichnotaxa

Because PBDB interval filters work at named stratigraphic intervals, the generator queries `Cambrian` through `Permian` and then applies a local numeric age filter so the retained records overlap the exact Paleozoic window.

## Outputs

Running the builder writes:

- `data/paleozoic-fauna-atlas.json`
- `data/paleozoic-fauna-atlas.js`
- `data/chunks/`
- `data/world-land.json`
- `data/world-land.js`

The publishable repository uses a chunked layout so each committed file stays comfortably below browser-upload limits on GitHub. The top-level atlas files are an index plus chunk manifest, and the species records are split across `data/chunks/*.json`.

## Rebuild

If the raw cache already exists:

```bash
python3 scripts/build_paleozoic_fauna_data.py
```

If you want to refresh the raw PBDB cache first:

```bash
curl -Lsf -o data/raw/pbdb-paleozoic-animal-taxa.csv 'https://paleobiodb.org/data1.2/taxa/list.csv?base_name=Animalia&rank=species&show=app,parent,size,class&interval=Cambrian,Permian&limit=all'
curl -Lsf -o data/raw/pbdb-paleozoic-animal-occurrences.csv 'https://paleobiodb.org/data1.2/occs/list.csv?base_name=Animalia&taxon_reso=species&show=coords,class,time&interval=Cambrian,Permian&limit=all'
curl -Lsf -o data/raw/world-land.geojson 'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_land.geojson'
```

The builder will also fetch any missing raw files automatically, so `data/raw/` does not need to be committed.

## Dataset shape

Each species record includes:

- taxonomic fields from phylum through genus where available
- a high-level fauna grouping for broad atlas browsing
- a clamped Paleozoic temporal range with period overlap metadata
- PBDB occurrence metadata
- aggregated mapped localities
- a generated summary description

## Sources

- Paleobiology Database taxonomic names API
- Paleobiology Database fossil occurrences API
- Natural Earth 1:110m land polygons for the map backdrop

## Repository layout

- `data/` contains the generated index, chunk files, and map assets
- `data/chunks/` contains species chunks sized for GitHub-friendly commits and uploads
- `data/raw/` is an optional local cache and is intentionally excluded from version control
- `scripts/` contains the generator
- `GITHUB_SETUP.md` contains quick push instructions for a new repository
