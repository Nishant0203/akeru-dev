"""One-time HS embedding index build scaffold."""

from __future__ import annotations

import argparse


SUPPORTED_PROVIDERS = {"openai", "voyage"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build HS index")
    parser.add_argument("--provider", default="openai", help="Embedding provider (openai|voyage)")
    args = parser.parse_args()

    provider = args.provider.lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise SystemExit(f"Unsupported provider: {provider}")

    print(f"HS index build stub complete using provider={provider}")


if __name__ == "__main__":
    main()
