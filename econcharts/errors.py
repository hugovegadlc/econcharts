"""Shared error base class for the econcharts pipeline.

All pipeline errors inherit from EconchartsError so callers can catch the
whole family with one clause, and the CLI doesn't need to enumerate every type.
"""


class EconchartsError(ValueError):
    """Base for all econcharts pipeline errors."""
