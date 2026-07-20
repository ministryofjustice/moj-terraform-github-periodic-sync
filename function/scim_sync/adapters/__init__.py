"""Adapters: the only code that talks to the outside world.

Everything here is **read-only**. There are deliberately no create/update/delete
methods, so a dry run cannot mutate GitHub or Identity Store even by accident.
"""
