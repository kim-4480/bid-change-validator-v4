"""Small read-only document QA, plus one disposable S3 write/read probe.

Run inside the API image after EC2 cutover. It never updates the database.
"""

import hashlib
import io
import os
from uuid import uuid4

from sqlalchemy import text

from app.config import get_settings
from app.database import engine
from app.services.document_extraction import extract_document
from app.services.document_storage import build_s3_client


settings = get_settings()
s3 = build_s3_client(region=settings.aws_region)
probe_key = f"qa/disposable-{uuid4().hex}.txt"
probe_bytes = b"bidcheck-s3-read-write-check\n"
try:
    s3.put_object(Bucket=settings.document_s3_bucket, Key=probe_key, Body=probe_bytes)
    actual = s3.get_object(Bucket=settings.document_s3_bucket, Key=probe_key)["Body"].read()
    assert actual == probe_bytes
    print("S3_WRITE_READ_OK")
finally:
    s3.delete_object(Bucket=settings.document_s3_bucket, Key=probe_key)

with engine.connect() as connection:
    connection.execute(text("SET TRANSACTION READ ONLY"))
    rows = connection.execute(text("""
        SELECT storage_key, file_sha256, name, content_type
        FROM notice_documents
        WHERE storage_key IS NOT NULL
          AND file_sha256 IS NOT NULL
          AND extraction_status = 'EXTRACTED'
          AND (lower(name) LIKE '%.pdf' OR lower(name) LIKE '%.hwp'
               OR lower(name) LIKE '%.hwpx')
        ORDER BY file_size_bytes ASC
    """)).mappings().all()

seen = set()
for row in rows:
    suffix = os.path.splitext(row["name"])[1].lower()
    if suffix in seen:
        continue
    try:
        body = s3.get_object(Bucket=settings.document_s3_bucket, Key=row["storage_key"])["Body"].read()
        assert hashlib.sha256(body).hexdigest() == row["file_sha256"]
        result = extract_document(io.BytesIO(body), filename=row["name"], content_type=row["content_type"])
        assert result.text.strip()
    except Exception as error:
        print("SAMPLE_SKIPPED", suffix, type(error).__name__)
        continue
    seen.add(suffix)
    print("S3_PARSE_OK", suffix, result.extractor, len(result.text))
    if seen == {".pdf", ".hwp", ".hwpx"}:
        break

assert seen == {".pdf", ".hwp", ".hwpx"}, f"missing successful parse type: {seen}"
