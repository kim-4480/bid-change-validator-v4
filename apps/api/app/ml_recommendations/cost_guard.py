"""No cloud training: explicit fail-closed remote data source guard."""
from __future__ import annotations
from urllib.parse import urlsplit

LOCAL_HOSTS={"localhost","127.0.0.1","::1","host.docker.internal"}

def require_isolated_data_url(url,allow_remote=False):
    host=urlsplit(url).hostname
    if not host:
        raise ValueError("A concrete database host is required")
    if host.lower() not in LOCAL_HOSTS and not allow_remote:
        raise ValueError("Remote DB exports are blocked by default. Create an approved, bounded snapshot first.")
    return True

def require_bounded_limit(limit):
    if not 1<=limit<=20000:
        raise ValueError("Source export must be bounded to 1..20000 rows")
    return limit
