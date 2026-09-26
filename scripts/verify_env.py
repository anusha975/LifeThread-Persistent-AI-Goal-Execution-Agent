#!/usr/bin/env python3
"""Environment configuration verification script for LifeThread platform.

Validates that all required environment variables defined in .env.example are present
in .env or system environment, WITHOUT ever printing or leaking secret values.
"""

import os
import sys
from pathlib import Path


def parse_env_file(filepath: Path) -> set[str]:
    """Extract declared variable keys from an environment file."""
    keys: set[str] = set()
    if not filepath.exists():
        return keys

    with open(filepath, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                if key:
                    keys.add(key)
    return keys


def main() -> int:
    root_dir = Path(__file__).resolve().parent.parent
    example_path = root_dir / ".env.example"
    env_path = root_dir / ".env"

    print("==================================================")
    print("LifeThread Environment Configuration Verification")
    print("==================================================")

    if not example_path.exists():
        print("ERROR: .env.example not found at project root.")
        return 1

    expected_keys = parse_env_file(example_path)
    present_keys = parse_env_file(env_path) if env_path.exists() else set()
    # Also check OS environment
    system_env_keys = set(os.environ.keys())
    active_keys = present_keys.union(system_env_keys)

    missing_keys = expected_keys - active_keys

    print(f"Total template variables expected: {len(expected_keys)}")
    print(f"File .env present: {'YES' if env_path.exists() else 'NO (using defaults/system)'}")

    if missing_keys:
        print("\n[WARNING] The following expected variables are missing from your configuration:")
        for k in sorted(missing_keys):
            print(f"  - {k}")
        print("\nPlease update your .env file using .env.example as a reference.")
        return 1

    print("\n[SUCCESS] All expected environment variables are declared.")
    print("Note: Secret values were verified for presence without leaking contents.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
