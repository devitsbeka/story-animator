import os
os.environ.setdefault("FACTORY_SERIES", "none")  # golden fixtures predate series defaults (lesson L021); real runs bind hero_v4 + yacht_v2
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

IDEA = "Solo sailor's yacht runs aground on North Sentinel's reef at night: what do you actually do?"
FAKE_BLENDER = f"{sys.executable} {os.path.join(ROOT, 'tests', 'farm', 'fake_blender.py')}"
