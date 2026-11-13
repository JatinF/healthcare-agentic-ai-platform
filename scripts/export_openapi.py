"""Write the FastAPI schema. Does not start a server."""

import json
from pathlib import Path

from healthcare_platform.api import create_app


def main() -> None:
    target = Path("api") / "openapi.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(create_app().openapi(), indent=2) + "\n", encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
