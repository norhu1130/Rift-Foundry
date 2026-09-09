"""Run the local Web UI with ``python -m lol_build.application.web``."""

from lol_build.application.web.server import main

if __name__ == "__main__":
    # Worker processes re-import this module under a different name, so the
    # server must start only for the process the user actually launched.
    main()
