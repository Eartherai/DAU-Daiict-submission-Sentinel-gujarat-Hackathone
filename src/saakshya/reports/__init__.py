"""Output reports: what the platform hands to a person who was not at the screen.

The ANPR read report, the printable vehicle-trace report and the audit export
live here, apart from the routes, so the command-line tool that writes the
submission's report and the endpoint an officer clicks produce the same rows
from the same code.
"""
from saakshya.reports.anpr import ANPR_COLUMNS, LEGACY_COLUMNS, anpr_csv, anpr_rows

__all__ = ["ANPR_COLUMNS", "LEGACY_COLUMNS", "anpr_csv", "anpr_rows"]
