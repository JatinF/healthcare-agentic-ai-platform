"""Console entry points."""

import sys

import uvicorn

from healthcare_platform.api import create_app
from healthcare_platform.demo import run_demo


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "demo"
    if command == "serve":
        uvicorn.run(create_app(), host="127.0.0.1", port=8000)
        return
    if command == "demo":
        sys.stdout.write(run_demo())
        return
    raise SystemExit(f"unknown command {command}")


if __name__ == "__main__":
    main()
