"""Write api/openapi.json, the contract `pnpm gen:api` turns into web/src/lib/api-types.ts."""

import json
from pathlib import Path

from app.main import create_app

out = Path(__file__).resolve().parents[1] / "openapi.json"
out.write_text(
    json.dumps(create_app().openapi(), indent=1, sort_keys=True) + "\n", encoding="utf-8"
)
print(f"wrote {out}")
