"""TLS fingerprint helper.

Fetches and prints the server leaf certificate SHA-256 fingerprint for TLS pinning.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from shared.tls_pinning import sha256_fingerprint_for_server


def main() -> None:
    p = argparse.ArgumentParser(description="Print SHA-256 fingerprint for a TLS server leaf certificate")
    p.add_argument("host")
    p.add_argument("port", type=int)
    args = p.parse_args()

    fp = sha256_fingerprint_for_server(args.host, args.port)
    print(fp)


if __name__ == "__main__":
    main()
