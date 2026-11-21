"""Repository paths used by the director (all absolute, derived from this file's location)."""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
RECIPES = os.path.join(ROOT, "factory", "recipes")
CATALOG = os.path.join(ROOT, "factory", "library", "catalog.json")
SOURCES = os.path.join(ROOT, "factory", "library", "sources")
SCHEMAS = os.path.join(HERE, "schemas")
FIXTURES = os.path.join(HERE, "fixtures")
EPISODE_SCHEMA = os.path.join(ROOT, "cloud", "spec", "episode.schema.json")
ACTING_PY = os.path.join(ROOT, "cloud", "blender", "acting.py")
PROPS_PY = os.path.join(ROOT, "cloud", "blender", "props.py")
RENDER_PY = os.path.join(ROOT, "cloud", "blender", "render_episode.py")
SENTINEL_GEO = os.path.join(ROOT, "studio", "src", "data", "sentinel_geo.json")
