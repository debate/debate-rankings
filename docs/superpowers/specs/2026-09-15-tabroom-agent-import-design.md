# Tabroom Agent Import Design

## Purpose

Enable a user to ask an AI agent in chat to import one published Tabroom event into the debate rankings project. The agent will collect the event field and all published round results, store normalized tournament data, update ranking configuration, recompute rankings, and verify the result.

The user does not run a dedicated importer command or provide Tabroom credentials to the repository.

## User Request

A request supplies:

- A Tabroom tournament URL containing `tourn_id`.
- A Tabroom event URL containing `event_id`, or enough event context to select one event from the tournament.
- A repository slug for the tournament.
- An optional ranking format override.

Example:

```text
Import this tournament into debate rankings:
Tournament: https://www.tabroom.com/index/tourn/index.mhtml?tourn_id=40313
Event: https://www.tabroom.com/index/tourn/fields.mhtml?tourn_id=40313&event_id=383405
Slug: ukso
```

If the event URL omits `event_id` and the conversation does not identify one event unambiguously, the agent asks the user to select an event. The initial acceptance case uses event `383405`, `Lincoln-Douglas - TOC Bid Event`, from the preceding conversation context.

## Agent Workflow

Project instructions will define a repeatable workflow for any agent working in this repository:

1. Parse and cross-check the tournament and event identifiers.
2. Use the user's authenticated Tabroom browser session.
3. Confirm that the loaded tournament and event match the request.
4. Read the complete event field.
5. Discover every published round result linked for that event.
6. Read rounds sequentially with a small delay between page requests.
7. Normalize and validate all collected data before changing active rankings inputs.
8. Write the tournament files, update configuration, recompute rankings, and run tests.
9. Report the imported event, entry count, round count, output paths, and any excluded rows.

If Tabroom redirects to login, the agent asks the user to log in and resumes after authentication. Credentials and browser session material are never written to the repository.

## Format Inference

The agent infers the ranking format from the event name:

- Names containing `Lincoln-Douglas` map to `hsld`.
- Names containing `Public Forum` map to `hspf`.
- Names containing `Policy` require an explicit override unless repository context makes the target unambiguous.

The user may always provide a format override. Supported formats initially match existing configuration files: `hsld`, `hspf`, and `cpd`.

## Stored Data

The importer writes a directory at:

```text
tournaments/<format>/<slug>/
```

The directory contains:

- `entries.csv`, with at least `Institution`, `Location`, `Entry`, and `Code`.
- One CSV per published round, named with a sortable ordinal, normalized round name, and Tabroom round ID.
- `tabroom.json`, recording the source tournament URL, event URL, tournament ID, event ID, event name, import time, and round metadata.

Round filenames sort in tournament order so the existing ranking system processes them chronologically. Source metadata makes later audits and refreshes reproducible.

## Normalization

The field table is normalized to the columns expected by `player_utils.py`. Round tables are normalized to the columns expected by `RankingSystem.run_round`:

- Lincoln-Douglas and Policy use `Aff`, `Neg`, and `Win`.
- Public Forum may use `Pro` and `Con`; the existing ranking system converts these to `Aff` and `Neg`.
- Judge, points, votes, and other published columns are retained when available.
- Bye rows and rows without a recognized winner remain safe for the existing ranking logic to skip.

HTML presentation details and decorative characters are not stored.

## Validation and Safe Updates

Before replacing tournament data or editing configuration, the helper validates:

- Tournament ID and event ID consistency.
- A nonempty field with unique entry codes.
- Required field and round columns.
- Each non-bye round participant against an entry code.
- Winners against the supported side labels.
- Unique round IDs and deterministic round order.
- A safe slug containing lowercase letters, numbers, and hyphens only.

All files are staged in a temporary directory. The active tournament directory and config change only after validation succeeds. An existing slug is not overwritten unless the user explicitly requests a refresh. A failed import leaves current tournament inputs, configuration, and ranking outputs unchanged.

## Configuration and Ranking Recalculation

After validation, the agent adds the slug to the inferred format's `tournaments` list if absent. New tournaments are appended by default because imports normally occur chronologically. If the tournament belongs earlier in the season, the agent asks for placement before changing the list.

The agent then runs the existing ranking pipeline and test suite. Success requires:

- The imported tournament is processed without missing-file or missing-code errors.
- Ranking outputs are regenerated for the selected format.
- Existing automated tests pass.
- Generated output CSVs are nonempty.

## Components

### Project Agent Instructions

A repository instruction file recognizes chat requests containing tournament, event, and slug inputs and directs the agent through authentication, collection, validation, and verification.

### Tabroom Import Helper

A focused Python module provides deterministic behavior for:

- Parsing identifiers and validating slugs.
- Inferring formats.
- Converting browser-extracted tables to normalized CSV data.
- Validating entries and rounds.
- Staging and installing tournament files.
- Updating the selected config without duplicates.

Browser navigation remains agent-driven. This avoids storing credentials or coupling the repository to a particular browser profile.

### Existing Ranking Pipeline

The existing `RankingSystem` remains the authority for rating computation. The import helper prepares its expected inputs and invokes the current application entry point rather than duplicating ranking logic.

## Testing

Unit tests cover URL parsing, format inference and override behavior, slug validation, table normalization, round ordering, participant validation, duplicate handling, configuration updates, and failure atomicity.

A fixture-based integration test uses representative saved field and round table data without accessing Tabroom. The live acceptance test imports tournament `40313`, event `383405`, under slug `ukso`, then verifies 231 entries, all 13 published rounds, successful ranking recomputation, and passing tests.

## Scope Limits

The first version imports one requested event at a time. It does not discover tournaments on a schedule, store Tabroom credentials, bypass authentication, import unpublished results, or automatically resolve ambiguous Policy formats. Batch discovery and refresh scheduling can be added after the single-event workflow is proven reliable.
