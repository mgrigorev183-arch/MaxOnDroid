"""Core layer: talks to adb and keeps local state. Knows nothing about the UI.

Everything in this package is importable without Qt so that future front ends
(another desktop toolkit, a CLI, tests) can reuse it.
"""
