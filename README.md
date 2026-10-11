# feedwire

A tiny RSS/Atom → Telegram/Discord forwarder core written with the **Python
standard library only** (`urllib`, `xml.etree`, `sqlite3`, `argparse`, `json`).
There are no third-party dependencies and nothing to `pip install`.

`feedwire` keeps a local SQLite database (`feed.db`) of the feeds you follow and
the last item it has seen for each one. Running `check` fetches every feed,
parses its RSS/Atom items, and prints the items that are new since the last run
so a bot can forward them to Telegram or Discord.

## What it does

- Stores feeds and the last-seen item (`last_guid`) in `feed.db`
  (tables: `feeds[id, url, name, last_guid]` and `state`).
- Fetches and parses both RSS (`<item>`) and Atom (`<entry>`).
- Prints new items as `[NEW] feed-name :: title :: link`.
- De-duplicates: an item is only reported once.
- Tolerates failures: a bad feed on `check` prints `ERROR fetch failed <url>`
  and continues with the remaining feeds.

## Setup

Requires Python 3.8+ (uses `sqlite3`, `urllib`, `xml.etree`). No installation.

```
git clone <this repo> feedwire
cd feedwire
python3 feedwire.py --help
```

The database (`feed.db`) is created automatically on first use.

## Run

```
# Add a feed (name is optional)
python3 feedwire.py add https://example.com/feed.xml "Example Blog"

# List configured feeds
python3 feedwire.py list

# Remove a feed by id
python3 feedwire.py remove 1

# Fetch everything and print new items
python3 feedwire.py check

# Print at most the 5 newest new items (default: all)
python3 feedwire.py check --limit 5

# Single-shot run (same as check, exits 0) — use from cron / a bot loop
python3 feedwire.py run --once
```

## Commands

| Command | Description | Exit codes |
| --- | --- | --- |
| `add <rss-url> [name]` | Add an RSS/Atom feed (URL, `file://`, or local path). | `0` ok, `2` bad feed/unreachable, `1` duplicate |
| `list` | List configured feeds and their ids. | `0` (including "no feeds configured") |
| `remove <id>` | Remove the feed with the given id. | `0` ok, `1` unknown id |
| `check [--limit N]` | Fetch all feeds; print new items since `last_guid`; update state. `--limit N` prints at most `N` items. | `0` (network failures are reported and skipped), `2` bad `--limit` |
| `run --once` | Same as `check`, single shot. | `0` |
| `--help` | Show usage. | `0` |

## Behaviour details

- **Empty database:** `check` prints `no feeds configured` and exits `0`.
- **Bad feed on `add`:** prints `ERROR bad feed: <url>` and exits `2`.
- **Network failure on `check`:** prints `ERROR fetch failed <url>` and keeps
  going with the other feeds (still exits `0`).
- **Newest-first assumption:** feeds are read newest first (standard for RSS and
  Atom). New items are those appearing before the stored `last_guid`. If the
  stored guid is no longer present (feed rotated), all items are treated as new.
- **Capping output:** `check --limit N` prints at most `N` `[NEW]` lines across
  all feeds; `N` must be a positive integer or the command exits `2`. State is
  still updated as usual, so de-duplication is unchanged.
- **Local testing:** `add` accepts `file://` URLs and plain filesystem paths,
  which is handy for offline testing.
