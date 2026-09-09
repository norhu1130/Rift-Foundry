"""Local Web UI for the offline matchup and recommendation engine."""

from lol_build.application.web.server import create_server
from lol_build.application.web.service import WebService

__all__ = ["WebService", "create_server"]
