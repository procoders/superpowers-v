#!/usr/bin/env python3
from __future__ import annotations

import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cvcore.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
