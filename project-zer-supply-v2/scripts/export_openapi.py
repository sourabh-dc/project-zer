from __future__ import annotations

import json
from pathlib import Path

from supply_v2.api import app


def main() -> None:
    target = Path("docs/openapi.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(app.openapi(), indent=2))
    print(str(target))


if __name__ == "__main__":
    main()
