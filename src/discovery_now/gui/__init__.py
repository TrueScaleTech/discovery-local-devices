"""The desktop app.

Everything that decides what the window shows lives in :mod:`.viewmodel`, which has
no Qt in it and is tested without a display. The rest of this package is the thin
layer that draws it.

PySide6 is an optional dependency (``pip install "discovery-now[gui]"``), so the
command line stays light and nothing outside this package imports it.
"""
