"""Registered checks for the lead's lessons L020 (EEVEE only with a real GPU) and L021 (series hero-tier assets)."""
import ast
import ctypes
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _egl_available():
    src = open(os.path.join(ROOT, "cloud", "blender", "render_episode.py")).read()
    fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "egl_available")
    ns = {"os": os, "sys": sys, "ctypes": ctypes}
    exec(compile(ast.Module([fn], []), "render_episode.py", "exec"), ns)
    return ns["egl_available"]


def test_l020_no_gpu_means_no_eevee(monkeypatch):
    f = _egl_available()
    monkeypatch.delenv("FORCE_EEVEE", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    real = os.path.exists
    monkeypatch.setattr(os.path, "exists", lambda p: False if p.startswith(("/proc/driver/nvidia", "/dev/nvidia", "/dev/dri")) else real(p))
    assert f() is False                       # libEGL on disk alone is not enough (the EGL_BAD_MATCH defect)
    monkeypatch.setenv("FORCE_EEVEE", "1")
    assert f() is True


def test_l021_series_defaults_bind_hero_tier(monkeypatch):
    from factory.director import compile as C
    monkeypatch.delenv("FACTORY_SERIES", raising=False)
    s = C._series_defaults()
    assert s["hero"]["key"] == "hero_v4" and s["props"]["yacht"] == "proc:yacht_v2"
    monkeypatch.setenv("FACTORY_SERIES", "none")
    assert C._series_defaults() is None
