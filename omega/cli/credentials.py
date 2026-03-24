#!/usr/bin/env python3
"""
omega credentials status

Show all registered credentials and their resolution status.

Usage:
    python -m omega.cli.credentials
    # or via entry point:
    omega-credentials
"""

from __future__ import annotations

import contextlib
import sys

# Import nodes to trigger credential registration side-effects.
# Each import registers its credentials with the singleton store.
_SIDE_EFFECT_MODULES = [
    "omega.core.brain",
    "omega.nodes.victoria.data_ingestion",
    "omega.nodes.victoria.vrp_data",
    "omega.nodes.polymarket.pricing",
]
for _mod in _SIDE_EFFECT_MODULES:
    with contextlib.suppress(Exception):
        __import__(_mod)

from omega.core.credentials import credentials  # noqa: E402


def main() -> int:
    items = credentials.status()
    if not items:
        print("No credentials registered.")
        return 0

    configured = sum(1 for i in items if i["configured"])
    total = len(items)

    print(f"\nOmega Credential Status ({configured}/{total} configured)\n")
    print(f"  {'NAME':<30} {'STATUS':<12} {'SOURCE':<10} DESCRIPTION")
    print("  " + "-" * 78)

    for item in items:
        if item["configured"]:
            status = "configured"
            icon = "✅"
        elif item["required"]:
            status = "MISSING"
            icon = "❌"
        else:
            status = "not set"
            icon = "⚠️ "

        source = item["source"] if item["configured"] else "-"
        print(f"  {icon} {item['name']:<28} {status:<12} {source:<10} {item['description']}")

    print()

    missing_required = [i for i in items if i["required"] and not i["configured"]]
    if missing_required:
        print("ERROR: Required credentials missing:")
        for i in missing_required:
            print(f"  - {i['name']}: {i['description']}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
