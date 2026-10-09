"""Materialize the AWS runtime configuration from narrowly scoped SSM secrets.

Run on the EC2 host. Never print secret values or commit the generated .env.
"""

import argparse
import json
import os
import subprocess
from pathlib import Path
from urllib.parse import quote


REGION = "ap-northeast-2"
REGISTRY = "226234259348.dkr.ecr.ap-northeast-2.amazonaws.com"
RDS_HOST = "bidcheck-dev.c1ya2qayagfc.ap-northeast-2.rds.amazonaws.com"
BUCKET = "bidcheck-dev-docs-226234259348-apne2"
SITE_DOMAIN = "15-165-249-43.sslip.io"
PARAMETERS = {
    "RDS_APP_PASSWORD": "/bidcheck/dev/rds/app-password",
    "G2B_SERVICE_KEY": "/bidcheck/dev/app/g2b-service-key",
    "OPENAI_API_KEY": "/bidcheck/dev/app/openai-api-key",
    "AUTH_BOOTSTRAP_ADMIN_USERNAME": "/bidcheck/dev/app/auth-admin-username",
    "AUTH_BOOTSTRAP_ADMIN_PASSWORD": "/bidcheck/dev/app/auth-admin-password",
}


def parameter(name: str) -> str:
    output = subprocess.check_output(
        ["aws", "ssm", "get-parameter", "--region", REGION,
         "--name", name, "--with-decryption", "--output", "json"],
        text=True,
    )
    return json.loads(output)["Parameter"]["Value"]


def env_value(value: str) -> str:
    if "\n" in value or "\r" in value:
        raise ValueError("multiline secrets are not supported")
    # Compose single-quoted .env values are literal, including '$'.
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("sha", help="immutable image tag")
    args = parser.parse_args()
    if len(args.sha) < 7 or any(char not in "0123456789abcdef" for char in args.sha):
        raise ValueError("image tag must be a Git commit SHA")
    secrets = {key: parameter(name) for key, name in PARAMETERS.items()}
    password = quote(secrets["RDS_APP_PASSWORD"], safe="")
    url = (
        f"postgresql+psycopg://bidcheck_app:{password}@{RDS_HOST}:5432/bidjigi"
        "?sslmode=verify-full&sslrootcert=/etc/ssl/certs/rds-global-bundle.pem"
    )
    values = {
        "API_IMAGE": f"{REGISTRY}/bidcheck-v4-api:{args.sha}",
        "WEB_IMAGE": f"{REGISTRY}/bidcheck-v4-web:{args.sha}",
        "RDS_DATABASE_URL": url,
        "DOCUMENT_S3_BUCKET": BUCKET,
        "SITE_DOMAIN": SITE_DOMAIN,
        **secrets,
    }
    target = Path("/opt/bidcheck/.env")
    temporary = target.with_suffix(".env.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        for key, value in values.items():
            output.write(f"{key}={env_value(value)}\n")
    os.replace(temporary, target)
    os.chmod(target, 0o600)
    print("AWS_ENV_READY", args.sha)


if __name__ == "__main__":
    main()
