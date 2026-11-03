---
name: fetch-tabroom
description: Download a tournament's entries list and every round's results CSV from Tabroom (via Claude in Chrome) into tournaments/<format>/<slug>/ and register it in the config. Use when the user asks to add, fetch, or pull a tournament from Tabroom.
---

# Fetch a tournament from Tabroom

The user is already signed in to Tabroom in Chrome. Load the `claude-in-chrome`
skill before the first browser call. Work in a new tab.

## Inputs

Ask only for what you cannot work out:

- **Tournament**: a Tabroom URL or name.
- **Event**: which division (e.g. Varsity LD). If the tournament has a separate
  round robin, treat it as its own tournament (see slug below).
- **Format folder**: `hsld` (LD), `hspf` (PF), `hscx` (HS policy), `cpd` (college policy).
- **Slug**: kebab-case short name, e.g. `heart-of-texas`, `nano-nagle`. Round
  robins get a `-rr` suffix (`greenhill-rr`). Before you use a slug, check the
  existing folders under `tournaments/<format>/` and reuse their naming style.
  If `tournaments/<format>/<slug>/` already exists, stop and ask before you
  overwrite anything.

Set `DEST=tournaments/<format>/<slug>` (relative to the repo root) and `mkdir -p` it.

## 1. Entries list

1. Open the tournament on Tabroom and find the entries/field list for the event.
2. Download the CSV export of the entries list for that event only.
3. Move the downloaded file from `~/Downloads` to `$DEST/entries.csv`. Use the
   newest matching file (`ls -t ~/Downloads | head`).
4. Check the header. It must have at least `Institution,Location,Entry,Code`
   (Tabroom also adds `Status,Record`). Do not add a `hash` column; the code
   writes that itself.

## 2. Round results

1. Open the event's results page and list every round in order: prelims, then
   elims (runoffs, triples, doubles, octas, quarters, semis, finals). Write down
   each round's name and its Tabroom round id (the `round_id` in the URL).
2. For each round, download its results CSV. Tabroom names these
   `Tabroom-<round_id>.csv`. Move each one from `~/Downloads` into `$DEST`.
   Download them one at a time and move each file before you start the next,
   so files don't get mixed up or saved as `(1)` duplicates.
3. Every round CSV starts with `Aff,Neg,Judge,Win,...`. Delete and re-download
   any file that doesn't (for example an HTML error page).

### Round order (important)

`src/main.py` processes round files in **alphabetical filename order**, and
results depend on that order.

- If the round ids increase in the same order as the rounds, keep the
  `Tabroom-<round_id>.csv` names.
- Otherwise rename **every** round file to `NN-<round-slug>-<round_id>.csv`, e.g.
  `01-round-1-1543295.csv`, `07-runoff-1543297.csv`, `13-finals-1543298.csv`
  (see `tournaments/hsld/ukso/` for an example).

## 3. Register in config

Add the slug to `"tournaments"` in `config/<format>-config.json` in
**chronological** order, which is not always the end of the list. A round robin
goes right before its main tournament (`"greenhill-rr", "greenhill"`). If you
can't tell where it goes, ask. Don't touch `majors` unless the user says so.

## 4. Verify

Run `.venv/bin/python src/main.py` from the repo root.

If it raises `has unmapped ... entries`, Tabroom's entries export left out teams
that dropped during the tournament. For each code it lists, add a row to
`entries.csv`. Fill `Institution,Location,Entry,Code` from the tournament's
public entries or results pages, and leave the other columns empty. If you can't
find the details, use the code as the Entry, like this:
`Success Academy HSLA-MANHATTAN,NY/US,Success Academy HSLA-MANHATTAN LT,Success Academy HSLA-MANHATTAN LT,`
Then run it again until it succeeds.

## Done

Report the folder, the number of rounds you downloaded (with the first and last
round names), any rows you added by hand, and where you placed the slug in the
config. Don't commit unless the user asks.
