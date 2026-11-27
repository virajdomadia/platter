// pnpm gen:api — api/openapi.json (FastAPI) → src/lib/api-types.ts. Committed; not CI-gated.
import { execSync } from "node:child_process";

execSync("uv run python -m scripts.dump_openapi", { cwd: "../api", stdio: "inherit" });
execSync("pnpm exec openapi-typescript ../api/openapi.json -o src/lib/api-types.ts", { stdio: "inherit" });
