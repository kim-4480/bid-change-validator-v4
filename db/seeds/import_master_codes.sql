\set QUIET 1
\pset pager off
SET TIME ZONE 'UTC';

CREATE TEMP TABLE master_code_import_stage (
    code TEXT,
    name TEXT,
    active TEXT,
    changed_at TEXT,
    source_window TEXT,
    collected_at TEXT,
    raw_json TEXT
);

\set QUIET 0
\echo 'Importing industry codes...'
\set QUIET 1
BEGIN;
\copy master_code_import_stage (code, name, active, changed_at, source_window, collected_at, raw_json) FROM '/data/master/industry_codes.csv' WITH (FORMAT CSV, HEADER TRUE, ENCODING 'UTF8')

INSERT INTO industry_codes (
    code,
    name,
    active,
    changed_at,
    source_window,
    collected_at,
    raw_json
)
SELECT
    BTRIM(code),
    BTRIM(name),
    COALESCE(UPPER(BTRIM(active)) = 'Y', FALSE),
    NULLIF(BTRIM(changed_at), '')::TIMESTAMPTZ,
    NULLIF(BTRIM(source_window), ''),
    BTRIM(collected_at)::TIMESTAMPTZ,
    COALESCE(NULLIF(BTRIM(raw_json), '')::JSONB, '{}'::JSONB)
FROM master_code_import_stage
WHERE NULLIF(BTRIM(code), '') IS NOT NULL
  AND NULLIF(BTRIM(name), '') IS NOT NULL
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    active = EXCLUDED.active,
    changed_at = EXCLUDED.changed_at,
    source_window = EXCLUDED.source_window,
    collected_at = EXCLUDED.collected_at,
    raw_json = EXCLUDED.raw_json;

TRUNCATE master_code_import_stage;
COMMIT;

\set QUIET 0
\echo 'Importing product codes...'
\set QUIET 1
BEGIN;
\copy master_code_import_stage (code, name, active, changed_at, source_window, collected_at, raw_json) FROM '/data/master/product_codes.csv' WITH (FORMAT CSV, HEADER TRUE, ENCODING 'UTF8')

INSERT INTO product_codes (
    code,
    name,
    active,
    changed_at,
    source_window,
    collected_at,
    raw_json
)
SELECT
    BTRIM(code),
    BTRIM(name),
    COALESCE(UPPER(BTRIM(active)) = 'Y', FALSE),
    NULLIF(BTRIM(changed_at), '')::TIMESTAMPTZ,
    NULLIF(BTRIM(source_window), ''),
    BTRIM(collected_at)::TIMESTAMPTZ,
    COALESCE(NULLIF(BTRIM(raw_json), '')::JSONB, '{}'::JSONB)
FROM master_code_import_stage
WHERE NULLIF(BTRIM(code), '') IS NOT NULL
  AND NULLIF(BTRIM(name), '') IS NOT NULL
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    active = EXCLUDED.active,
    changed_at = EXCLUDED.changed_at,
    source_window = EXCLUDED.source_window,
    collected_at = EXCLUDED.collected_at,
    raw_json = EXCLUDED.raw_json;

TRUNCATE master_code_import_stage;
COMMIT;

\set QUIET 0
\echo 'Importing institution codes...'
\set QUIET 1
BEGIN;
\copy master_code_import_stage (code, name, active, changed_at, source_window, collected_at, raw_json) FROM '/data/master/institution_codes.csv' WITH (FORMAT CSV, HEADER TRUE, ENCODING 'UTF8')

INSERT INTO institution_codes (
    code,
    name,
    active,
    changed_at,
    source_window,
    collected_at,
    raw_json
)
SELECT
    BTRIM(code),
    BTRIM(name),
    COALESCE(UPPER(BTRIM(active)) = 'Y', FALSE),
    NULLIF(BTRIM(changed_at), '')::TIMESTAMPTZ,
    NULLIF(BTRIM(source_window), ''),
    BTRIM(collected_at)::TIMESTAMPTZ,
    COALESCE(NULLIF(BTRIM(raw_json), '')::JSONB, '{}'::JSONB)
FROM master_code_import_stage
WHERE NULLIF(BTRIM(code), '') IS NOT NULL
  AND NULLIF(BTRIM(name), '') IS NOT NULL
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    active = EXCLUDED.active,
    changed_at = EXCLUDED.changed_at,
    source_window = EXCLUDED.source_window,
    collected_at = EXCLUDED.collected_at,
    raw_json = EXCLUDED.raw_json;

COMMIT;
\set QUIET 0

\echo 'Master data import complete.'
SELECT 'industry' AS type, COUNT(*) AS row_count FROM industry_codes
UNION ALL
SELECT 'product', COUNT(*) FROM product_codes
UNION ALL
SELECT 'institution', COUNT(*) FROM institution_codes
ORDER BY type;
