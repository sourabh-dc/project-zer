from __future__ import annotations

import json
import shutil
from pathlib import Path

from supply_v2.api import app


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    site = ROOT / "site"
    site.mkdir(exist_ok=True)
    docs_site = site / "docs"
    docs_site.mkdir(parents=True, exist_ok=True)

    (site / "index.html").write_text(
        """<!doctype html>
<html><head><meta charset="utf-8"><title>Supply V2 Docs</title></head>
<body>
<h1>Supply V2 Docs</h1>
<ul>
  <li><a href="docs/README.md">README</a></li>
  <li><a href="docs/code-guide.md">Code Guide</a></li>
  <li><a href="docs/api-reference.md">API Guide</a></li>
  <li><a href="docs/openapi.json">OpenAPI JSON</a></li>
  <li><a href="docs/business-scenarios.md">Business Scenarios</a></li>
  <li><a href="docs/dispute-flow.md">Dispute Flow</a></li>
  <li><a href="docs/opa-policy-guide.md">OPA Policy Guide</a></li>
  <li><a href="docs/production-rollout.md">Production Rollout</a></li>
  <li><a href="docs/pending-vs-plan.md">Pending vs Plan</a></li>
</ul>
</body></html>""",
        encoding="utf-8",
    )

    for source in [ROOT / "README.md", *sorted((ROOT / "docs").glob("*"))]:
        if source.is_file():
            target = docs_site / source.name
            shutil.copyfile(source, target)

    (docs_site / "openapi.json").write_text(json.dumps(app.openapi(), indent=2), encoding="utf-8")
    print(str(site))


if __name__ == "__main__":
    main()
