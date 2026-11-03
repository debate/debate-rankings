---
name: fetch-tabroom
description: Download a tournament's entries list and every round's results CSV from Tabroom (via the built-in Claude browser) into tournaments/<format>/<slug>/ and register it in the config. Use when the user asks to add, fetch, or pull a tournament from Tabroom.
---

# Fetch a tournament from Tabroom

The user is signed in to Tabroom in the built-in Claude browser (the
`mcp__Claude_Browser__*` tools), not Chrome. Load the `built-in-browser` skill
before the first browser call, and open Tabroom with `preview_start` and a `url`.

Downloads from the browser pane do not reach `~/Downloads`. Do not click the
export buttons. Instead, capture the CSV text in the page with
`javascript_tool` and write the files yourself (see "Capturing a CSV" below).

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

1. Open the event's field page:
   `/index/tourn/fields.mhtml?tourn_id=<tourn_id>&event_id=<event_id>`. The
   event ids are the options of the event `<select>` on the results page.
2. Capture the `fieldsort` table and write it to `$DEST/entries.csv`.
3. Check that the row count matches the "N entries" count on the page.
4. Check the header. It must have at least `Institution,Location,Entry,Code`
   (Tabroom also adds `Status,Record`). Do not add a `hash` column; the code
   writes that itself.

## 2. Round results

1. Open the event's results page and list every round in order: prelims, then
   elims (runoffs, triples, doubles, octas, quarters, semis, finals). Write down
   each round's name and its Tabroom round id (the `round_id` in the URL).
2. Capture each round's table (its id is the round id) on
   `/index/tourn/results/round_results.mhtml?tourn_id=<tourn_id>&round_id=<round_id>`
   and write it to `$DEST/Tabroom-<round_id>.csv`.
3. Every round CSV starts with `Aff,Neg,Judge,Win` (prelims) or
   `Aff,Neg,Judges,Votes,Win` (elims). Recapture any that doesn't.

### Capturing a CSV

Tabroom's export button runs the tablesorter `output` widget. Set its callback
to keep the text instead of downloading it, then click the button:

```js
const c = document.getElementById(TABLE_ID).config;
c.widgetOptions.output_saveRows = 'all';
c.widgetOptions.output_callback = (cfg, data) => { window.__csv = data; return false; };
document.getElementById('output_' + TABLE_ID).click();
```

To get every round in one call, load each round page in an off-screen iframe
(`position:absolute;left:-5000px`, not `display:none`), run the same code on
`iframe.contentWindow`, and collect the results into one object. Values on
`window` are lost when the tab navigates, so return them in the same call.

To move the text to disk: return `JSON.stringify` of `{name: {len, body}}`.
Elim cells contain long runs of tabs, so shorten them in the body
(``body.replace(/\t+/g, m => `<T${m.length}>`)``) and expand them again when you
write. Save the JSON to the scratchpad with Write, then write each file with a
short Python script that expands the tabs and checks that each file's length
equals `len`. Recapture any file that fails the check.

### Round order (important)

`src/main.py` processes round files in **alphabetical filename order**, and
results depend on that order.

- If the round ids increase in the same order as the rounds, keep the
  `Tabroom-<round_id>.csv` names.
- Otherwise rename **every** round file to `NN-<round-slug>-<round_id>.csv`, e.g.
  `01-round-1-1543295.csv`, `07-runoff-1543297.csv`, `13-finals-1543298.csv`
  (see `tournaments/hsld/ukso/` for an example).

## 3. Register in config

Add `"<slug>": "<YYYY-MM-DD>"` to the `"tournaments"` map in
`config/<format>-config.json`, using the event's start date from Tabroom (for a
round robin, use the day before its main tournament starts). The code sorts
tournaments by this date. Entries with the same date run in file order. Don't touch `majors` unless the user says so.

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
