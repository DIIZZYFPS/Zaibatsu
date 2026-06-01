#!/usr/bin/env python3
"""
Zaibatsu Launcher - Avoids package name collision by using run.py
"""

import sys

# Ensure Python version is compatible
if sys.version_info < (3, 8):
    sys.exit("Error: Zaibatsu requires Python 3.8 or higher.")

from zaibatsu.cli import main

if __name__ == "__main__":
    main()
