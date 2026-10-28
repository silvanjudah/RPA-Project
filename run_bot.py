#!/usr/bin/env python3
"""Entry point - the bot's equivalent of UiPath's Main.xaml."""

from __future__ import annotations

import sys

from rpa_jobs.cli import main

if __name__ == "__main__":
    sys.exit(main())
