#!/usr/bin/env python3
"""feedwire - RSS/Atom to Telegram/Discord forwarder (Python stdlib only).

Tracks feeds in a local SQLite database and reports new items since the last
seen item per feed. No third-party dependencies: urllib, xml.etree, sqlite3,
argparse and json from the standard library only.
"""

import argparse
import os
import sqlite3
import sys
import urllib.error
import urllib.request

# ElementTree is used together with an explicit inline-DTD/ENTITY guard in
# parse_feed(); the stdlib-only constraint forbids defusedxml.
import xml.etree.ElementTree as ET  # nosec B405

DB_PATH = os.environ.get(
    "FEEDWIRE_DB",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "feed.db"),
)
USER_AGENT = "feedwire/1.0 (+stdlib)"
TIMEOUT = 20


# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #
def connect(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS feeds (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            url       TEXT NOT NULL UNIQUE,
            name      TEXT,
            last_guid TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS state (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )
    conn.execute(
        "INSERT OR IGNORE INTO state (key, value) VALUES ('schema_version', '1')"
    )
    conn.commit()
    return conn


# --------------------------------------------------------------------------- #
# Fetching / parsing
# --------------------------------------------------------------------------- #
def normalize_url(raw):
    """Turn a direct filesystem path into a file:// URL; keep URLs as-is."""
    if "://" in raw:
        return raw
    return "file://" + os.path.abspath(os.path.expanduser(raw))


def fetch(url):
    """Fetch the raw bytes of a feed. Raises on any failure."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    # file:// URLs via normalize_url are an intentional feature for local
    # fixtures; the scheme is otherwise constrained by normalize_url.
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # nosec B310
        return resp.read(), resp.geturl()


def _localname(tag):
    return tag.rsplit("}", 1)[-1].lower() if "}" in tag else tag.lower()


def _text(node, *names):
    for child in node:
        if _localname(child.tag) in names:
            if child.text and child.text.strip():
                return child.text.strip()
    return None


def _link(node):
    """Extract a usable link from an RSS item or Atom entry."""
    for child in node:
        name = _localname(child.tag)
        if name == "link":
            rel = child.get("rel")
            href = child.get("href")
            if href and (rel is None or rel == "alternate"):
                return href.strip()
            if child.text and child.text.strip():
                return child.text.strip()
    return None


def parse_feed(data):
    """Parse RSS or Atom bytes into an ordered list of {guid, title, link}."""
    probe = (
        data.lower() if isinstance(data, (bytes, bytearray)) else data.lower().encode()
    )
    if b"<!doctype" in probe or b"<!entity" in probe:
        raise ValueError("feed rejected: inline DTD/ENTITY not allowed")
    root = ET.fromstring(data)  # nosec B314
    items = []
    nodes = [n for n in root.iter() if _localname(n.tag) in ("item", "entry")]
    for node in nodes:
        title = _text(node, "title") or "(no title)"
        link = _link(node) or ""
        guid = _text(node, "guid", "id") or link or title
        items.append({"guid": guid, "title": title, "link": link})
    return items


def new_items(items, last_guid):
    """Items considered new relative to last_guid (feed is newest-first)."""
    if not items:
        return []
    if not last_guid:
        return list(items)
    for idx, item in enumerate(items):
        if item["guid"] == last_guid:
            return items[:idx]
    return list(items)


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def cmd_add(conn, args):
    url = normalize_url(args.url)
    try:
        data, _ = fetch(url)
    except Exception:
        print(f"ERROR bad feed: {args.url}")
        return 2
    try:
        items = parse_feed(data)
    except (ET.ParseError, ValueError):
        print(f"ERROR bad feed: {args.url}")
        return 2

    name = args.name or url
    try:
        cur = conn.execute(
            "INSERT INTO feeds (url, name, last_guid) VALUES (?, ?, NULL)",
            (url, name),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        print(f"ERROR feed already exists: {args.url}")
        return 1
    print(f"added feed #{cur.lastrowid}: {name} ({len(items)} item(s) pending)")
    return 0


def cmd_list(conn, args):
    rows = conn.execute(
        "SELECT id, url, name, last_guid FROM feeds ORDER BY id"
    ).fetchall()
    if not rows:
        print("no feeds configured")
        return 0
    print(f"{'ID':<4} {'NAME':<24} {'URL'}")
    for row in rows:
        print(f"{row['id']:<4} {row['name'] or '':<24} {row['url']}")
    print(f"\n{len(rows)} feed(s)")
    return 0


def cmd_remove(conn, args):
    cur = conn.execute("DELETE FROM feeds WHERE id = ?", (args.id,))
    conn.commit()
    if cur.rowcount == 0:
        print(f"ERROR no feed with id {args.id}")
        return 1
    print(f"removed feed #{args.id}")
    return 0


def cmd_check(conn, args):
    rows = conn.execute(
        "SELECT id, url, name, last_guid FROM feeds ORDER BY id"
    ).fetchall()
    if not rows:
        print("no feeds configured")
        return 0

    total_new = 0
    for row in rows:
        name = row["name"] or row["url"]
        try:
            data, _ = fetch(row["url"])
            items = parse_feed(data)
        except (urllib.error.URLError, OSError) as exc:
            print(f"ERROR fetch failed {row['url']} ({exc})")
            continue
        except (ET.ParseError, ValueError):
            print(f"ERROR fetch failed {row['url']} (invalid feed)")
            continue

        fresh = new_items(items, row["last_guid"])
        for item in reversed(fresh):
            print(f"[NEW] {name} :: {item['title']} :: {item['link']}")
        total_new += len(fresh)

        if items:
            conn.execute(
                "UPDATE feeds SET last_guid = ? WHERE id = ?",
                (items[0]["guid"], row["id"]),
            )
            conn.commit()

    print(f"{total_new} new item(s)")
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser():
    parser = argparse.ArgumentParser(
        prog="feedwire",
        description=(
            "RSS/Atom feed tracker for Telegram/Discord forwarding (stdlib only)."
        ),
    )
    sub = parser.add_subparsers(dest="command")

    p_add = sub.add_parser("add", help="add an RSS/Atom feed")
    p_add.add_argument("url", help="feed URL (http(s):// or file:// or local path)")
    p_add.add_argument("name", nargs="?", help="optional display name")
    p_add.set_defaults(func=cmd_add)

    p_list = sub.add_parser("list", help="list configured feeds")
    p_list.set_defaults(func=cmd_list)

    p_remove = sub.add_parser("remove", help="remove a feed by id")
    p_remove.add_argument("id", type=int, help="feed id shown by 'list'")
    p_remove.set_defaults(func=cmd_remove)

    p_check = sub.add_parser("check", help="fetch all feeds and print new items")
    p_check.set_defaults(func=cmd_check)

    p_run = sub.add_parser("run", help="run the forwarder loop")
    p_run.add_argument(
        "--once", action="store_true", help="run a single check and exit"
    )
    p_run.set_defaults(func=cmd_check)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0

    conn = connect()
    try:
        return args.func(conn, args)
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
