#!/usr/bin/env python3
"""LifeThread Demo Data Loader Script.

Module 46: Demo Data and Example Scenarios.

Populates or resets the database with 6 realistic long-running scenarios demonstrating:
1. Changing deadlines (SOC2 Type II Compliance)
2. Limited available time (Financial Ledger in Go)
3. Task failure & recovery (Zero-Downtime Database Migration)
4. Newly discovered weakness (Advanced Rust Systems Programming)
5. Blocked dependency (Zero-Trust Service Mesh)
6. Successful completion (pgvector Semantic RAG Engine)

Usage:
    python scripts/load_demo_data.py
    python scripts/load_demo_data.py --reset
    python scripts/load_demo_data.py --clear-only
    python scripts/load_demo_data.py --status
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Add backend directory to sys.path so app imports resolve properly
backend_dir = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal, close_db_engine
from app.demo.loader import DemoDataLoader
from app.demo.scenarios import DEMO_USER_EMAIL, DEMO_USER_PASSWORD


async def main_async() -> int:
    parser = argparse.ArgumentParser(
        description="LifeThread Module 46 Demo Dataset Loader",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        default=True,
        help="Clear existing demo data before loading fresh scenarios",
    )
    parser.add_argument(
        "--no-reset",
        action="store_false",
        dest="reset",
        help="Do not clear existing demo data before loading",
    )
    parser.add_argument(
        "--clear-only",
        action="store_true",
        help="Only delete demo data, do not seed fresh scenarios",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Display current demo data status and exit",
    )

    args = parser.parse_args()

    settings = get_settings()
    print("=" * 68)
    print("  LifeThread Autonomous AI Agent - Demo Dataset Manager (Module 46)")
    print(f"  Environment: {settings.ENVIRONMENT} | Allow Demo: {settings.ALLOW_DEMO_DATA}")
    print("=" * 68)

    if not DemoDataLoader.is_demo_allowed():
        print(f"\n[ERROR] Demo data operations are rejected in '{settings.ENVIRONMENT}' environment.")
        print("Set ALLOW_DEMO_DATA=True and ensure ENVIRONMENT != 'production' to proceed.\n")
        return 1

    async with AsyncSessionLocal() as session:
        if args.status:
            print("\nChecking current demo dataset status...")
            status_info = await DemoDataLoader.get_demo_status(session)
            print(f"  Loaded:        {status_info['is_loaded']}")
            print(f"  User Exists:   {status_info['user_exists']}")
            print(f"  User ID:       {status_info.get('user_id')}")
            print(f"  Goals Count:   {status_info['goals_count']}")
            print(f"  Memories Count:{status_info['memories_count']}")
            print()
            return 0

        if args.clear_only:
            print("\nClearing existing demo dataset...")
            cleared = await DemoDataLoader.clear_demo_data(session)
            print(f"  Goals deleted:    {cleared['goals_deleted']}")
            print(f"  Memories deleted: {cleared['memories_deleted']}")
            print("[SUCCESS] Demo dataset successfully cleared.\n")
            return 0

        print(f"\nLoading 6 realistic long-running scenarios for demo user: {DEMO_USER_EMAIL}...")
        result = await DemoDataLoader.load_demo_scenarios(
            session=session,
            reset_existing=args.reset,
        )

        print("\n[SUCCESS] Demo Dataset Successfully Seeded!")
        print(f"  User ID:             {result['user_id']}")
        print(f"  User Email:          {result['user_email']}")
        print(f"  Goals Created:       {result['goals_created']}")
        print(f"  Tasks Created:       {result['tasks_created']}")
        print(f"  Dependencies:        {result['dependencies_created']}")
        print(f"  Plans Created:       {result['plans_created']}")
        print(f"  Memories Created:    {result['memories_created']}")
        print("\nDemonstrated Scenarios:")
        for sc in result["scenarios"]:
            print(f"  - [{sc['scenario_name'].upper()}] {sc['goal_title']} (Status: {sc['status']})")

        print("\nDemo Login Credentials:")
        print(f"  Email:    {DEMO_USER_EMAIL}")
        print(f"  Password: {DEMO_USER_PASSWORD}")
        print("=" * 68 + "\n")

    return 0


def main() -> None:
    try:
        code = asyncio.run(main_async())
    finally:
        asyncio.run(close_db_engine())
    sys.exit(code)


if __name__ == "__main__":
    main()
