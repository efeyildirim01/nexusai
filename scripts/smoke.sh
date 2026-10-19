#!/usr/bin/env bash
# End-to-end smoke test against a running stack (docker compose up), through the web BFF
# exactly as a browser would use it: sign up, upload a CSV, read the dashboard, run a
# query, and check that an attack query is blocked.
set -euo pipefail

WEB="${WEB_URL:-http://localhost:3000}"
JAR="$(mktemp)"
CSV="$(mktemp --suffix=.csv)"
trap 'rm -f "$JAR" "$CSV"' EXIT
H=(-H "x-nexus-csrf: 1")
slug="smoke-$(date +%s)"

step() { printf '\n== %s\n' "$*"; }
fail() { echo "FAIL: $*" >&2; exit 1; }

step "sign up ($slug)"
curl -fsS -c "$JAR" "${H[@]}" -H 'content-type: application/json' "$WEB/api/auth/signup" \
  -d "{\"company_name\":\"Smoke Test\",\"workspace\":\"$slug\",\"full_name\":\"Smoke\",\"email\":\"smoke@example.com\",\"password\":\"smoke-test-password-1\"}"

step "upload"
{
  echo "order_id,order_date,product,category,region,quantity,unit_price,status"
  for i in $(seq 1 300); do
    printf 'SO-%d,2025-%02d-%02d,Widget %d,Cat %d,Region %d,%d,%d.50,completed\n' \
      "$i" $(( (i % 12) + 1 )) $(( (i % 28) + 1 )) $(( i % 5 )) $(( i % 3 )) $(( i % 4 )) $(( (i % 4) + 1 )) $(( (i % 50) + 5 ))
  done
} > "$CSV"
upload=$(curl -fsS -b "$JAR" -c "$JAR" "${H[@]}" -F "file=@$CSV;type=text/csv" "$WEB/api/backend/datasets")
echo "$upload" | grep -q '"imported_rows":300' || fail "upload: $upload"

step "dashboard"
overview=$(curl -fsS -b "$JAR" "$WEB/api/backend/analytics/overview")
echo "$overview" | grep -q '"lines":300' || fail "overview: $overview"

step "sql console"
result=$(curl -fsS -b "$JAR" "${H[@]}" -H 'content-type: application/json' "$WEB/api/backend/ai/sql" \
  -d '{"sql":"SELECT region, SUM(revenue) AS revenue FROM sales GROUP BY region ORDER BY 2 DESC"}')
echo "$result" | grep -q '"row_count":4' || fail "sql: $result"

step "attack query is blocked"
code=$(curl -s -o /dev/null -w '%{http_code}' -b "$JAR" "${H[@]}" -H 'content-type: application/json' \
  "$WEB/api/backend/ai/sql" -d '{"sql":"SELECT password_hash FROM users"}')
[ "$code" = "422" ] || fail "expected 422, got $code"

step "write without CSRF header is refused"
code=$(curl -s -o /dev/null -w '%{http_code}' -b "$JAR" -H 'content-type: application/json' \
  "$WEB/api/backend/ai/sql" -d '{"sql":"SELECT 1"}')
[ "$code" = "403" ] || fail "expected 403, got $code"

step "exports"
curl -fsS -b "$JAR" -o /dev/null -w 'pdf %{http_code} %{size_download} bytes\n' "$WEB/api/backend/reports/sales.pdf"
curl -fsS -b "$JAR" -o /dev/null -w 'xlsx %{http_code} %{size_download} bytes\n' "$WEB/api/backend/reports/sales.xlsx"

echo; echo "Smoke test passed."
