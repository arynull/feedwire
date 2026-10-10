#!/usr/bin/env bash
# feedwire CI smoke test — stdlib only, no network (uses a local file:// feed).
set -euo pipefail
cd "$(dirname "$0")"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
export FEEDWIRE_DB="$WORK/smoke.db"

cat > "$WORK/feed.xml" <<'XML'
<?xml version="1.0"?>
<rss version="2.0"><channel><title>Smoke</title>
<item><guid>s1</guid><title>First</title><link>http://x/1</link></item>
<item><guid>s2</guid><title>Second</title><link>http://x/2</link></item>
</channel></rss>
XML

run() { python3 feedwire.py "$@"; }

echo "--- empty check ---"
run check | grep -q "no feeds configured"

echo "--- bad url ---"
run add not-a-url >/dev/null 2>&1 && { echo "FAIL: bad url accepted"; exit 1; } || true

echo "--- add + first check (2 NEW) ---"
run add "$WORK/feed.xml" smoke >/dev/null
OUT1="$(run check)"
echo "$OUT1" | grep -q "First" || { echo "FAIL: First missing"; exit 1; }
echo "$OUT1" | grep -q "Second" || { echo "FAIL: Second missing"; exit 1; }

echo "--- second check (dedup, 0 NEW) ---"
OUT2="$(run check)"
echo "$OUT2" | grep -q "0 new item(s)" || { echo "FAIL: dedup broken: $OUT2"; exit 1; }

echo "--- remove ---"
run remove 99 >/dev/null 2>&1 && { echo "FAIL: bad id accepted"; exit 1; } || true

echo "smoke OK"
