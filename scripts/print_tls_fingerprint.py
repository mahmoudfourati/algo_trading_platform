from __future__ import annotations

import argparse

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
