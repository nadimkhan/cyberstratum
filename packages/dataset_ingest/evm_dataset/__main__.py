"""Allow ``python -m evm_dataset`` to run the CLI.

The implementation lives in :mod:`evm_dataset.cli`; this module only
exists so the package can be invoked as a module.
"""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
