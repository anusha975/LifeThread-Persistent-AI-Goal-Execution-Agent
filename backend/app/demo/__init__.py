"""LifeThread Demo Data and Example Scenarios Module.

Module 46: Demo Data and Example Scenarios.
"""

from app.demo.loader import DemoDataLoader
from app.demo.scenarios import (
    DEMO_USER_EMAIL,
    DEMO_USER_NAME,
    DEMO_USER_PASSWORD,
    get_demo_scenarios_data,
)

__all__ = [
    "DEMO_USER_EMAIL",
    "DEMO_USER_NAME",
    "DEMO_USER_PASSWORD",
    "DemoDataLoader",
    "get_demo_scenarios_data",
]
