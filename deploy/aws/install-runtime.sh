#!/usr/bin/env bash
set -euo pipefail
umask 077

install -d -m 0700 /opt/bidcheck
aws s3 cp s3://bidcheck-dev-docs-226234259348-apne2/deploy/runtime.tar.gz \
  /opt/bidcheck/runtime.tar.gz --region ap-northeast-2 --only-show-errors
tar -xzf /opt/bidcheck/runtime.tar.gz -C /opt/bidcheck
chmod 0700 /opt/bidcheck/deploy.sh
curl --fail --silent --show-error --location \
  https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem \
  -o /opt/bidcheck/rds-global-bundle.pem
chmod 0644 /opt/bidcheck/rds-global-bundle.pem
echo AWS_RUNTIME_INSTALLED
