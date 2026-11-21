import copy
import json
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

FX = os.path.join(ROOT, "factory", "director", "fixtures", "sentinel")


def load(name):
    with open(os.path.join(FX, name)) as fh:
        return json.load(fh)


@pytest.fixture
def story():
    return load("develop.2.json")


@pytest.fixture
def breakdown():
    return load("breakdown.1.json")


@pytest.fixture
def plan():
    return load("direct.1.json")


@pytest.fixture
def words():
    with open(os.path.join(ROOT, "episodes", "sentinel", "audio", "narration.words.json")) as fh:
        return json.load(fh)


@pytest.fixture
def manifest(breakdown):
    from factory.director import librarian
    man, _ = librarian.resolve(breakdown, ph=librarian.PolyHavenSearch(os.path.join(FX, "polyhaven_search.json")))
    return man


def rules(rep, blocking=True):
    return {i["rule"] for i in (rep.blocking if blocking else rep.issues)}


def deep(d):
    return copy.deepcopy(d)
