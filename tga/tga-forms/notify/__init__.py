"""Notifications, eLabFTW export and the ELN package for TGA requests.

Modules are imported explicitly by their users (``from notify import mailer``),
so importing this package stays cheap and does not pull in optional
dependencies such as matplotlib.
"""

__all__ = [
    "settings",      # configuration file(s) and per-user eLabFTW targets
    "mailer",        # SMTP sending plus the queue for "not configured yet"
    "templates",     # the notification texts
    "events",        # which event goes to whom
    "elabftw",       # instance independent eLabFTW export
    "eln_export",    # the ZIP for a manual ELN upload
    "entry_data",    # reading a request's parameters, curves and results
]
