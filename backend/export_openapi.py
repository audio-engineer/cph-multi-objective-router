"""Export OpenAPI specification."""

# pylint: disable=duplicate-code

import json
from pathlib import Path

from app.main import app

with Path("openapi.json").open("w", encoding="utf-8") as file:
    json.dump(app.openapi(), file, indent=2)
