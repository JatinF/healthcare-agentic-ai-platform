"""Measure local run time and the offline scorecards. Does not contact a network."""

import json
import platform
import statistics
import subprocess
from pathlib import Path

from healthcare_platform import __version__
from healthcare_platform.cases import CASES
from healthcare_platform.evaluation import score_behavior
from healthcare_platform.gates import adapter_report
from healthcare_platform.identity import REA_TOKEN, authenticate
from healthcare_platform.platform import Platform


def _cim(query: str) -> dict[str, object]:
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", query],
        check=True,
        capture_output=True,
        text=True,
    )
    loaded = json.loads(completed.stdout)
    if not isinstance(loaded, dict):
        raise RuntimeError("CIM query did not return an object")
    return loaded


def hardware() -> dict[str, object]:
    cpu = _cim(
        "Get-CimInstance Win32_Processor | Select-Object -First 1 "
        "Name,NumberOfCores,NumberOfLogicalProcessors | ConvertTo-Json -Compress"
    )
    memory = _cim(
        "Get-CimInstance Win32_OperatingSystem | Select-Object "
        "FreePhysicalMemory,TotalVisibleMemorySize | ConvertTo-Json -Compress"
    )
    return {
        "processor": cpu.get("Name"),
        "cores": cpu.get("NumberOfCores"),
        "logical_processors": cpu.get("NumberOfLogicalProcessors"),
        "free_physical_memory_kb": memory.get("FreePhysicalMemory"),
        "total_visible_memory_kb": memory.get("TotalVisibleMemorySize"),
        "python": platform.python_version(),
        "system": platform.system(),
    }


def main() -> None:
    actor = authenticate(REA_TOKEN)
    if actor is None:
        raise RuntimeError("requester fixture missing")
    walls: list[float] = []
    for index in range(30):
        case = CASES[index % len(CASES)]
        runtime = Platform()
        result = runtime.run(case.workflow_id, case.case_id, actor, run_id=f"bench-{index}")
        walls.append(float(result["wall_seconds"]))
    walls.sort()
    scores = {}
    for behavior in ("governed", "cheap", "leaky", "regressed"):
        matches, leaks = score_behavior(behavior)
        scores[behavior] = {
            "exact_matches": matches,
            "cases": len(CASES),
            "exact_match": matches / len(CASES),
            "phi_leaks": leaks,
        }
    report = {
        "version": __version__,
        "price": "none",
        "hardware": hardware(),
        "repeats": len(walls),
        "wall_seconds": {
            "min": walls[0],
            "p50": statistics.median(walls),
            "max": walls[-1],
        },
        "routing_units": {
            "note": "Configured routing units, not measured dollars and not the wall clock.",
            "mock-governed": {"quality": 0.95, "cost_units": 8, "latency_units": 30},
            "mock-alternate": {"quality": 0.96, "cost_units": 12, "latency_units": 40},
            "mock-cheap": {"quality": 0.78, "cost_units": 1, "latency_units": 5},
        },
        "quality_floor": 0.9,
        "scores": scores,
        "ehr_calls": 0,
        "adapters": adapter_report(),
        "docker": "not-run",
        "kubectl": "not-run",
        "grafana": "not-run",
        "live_model": "not-run",
        "temporal": "not-used",
    }
    target = Path("benchmarks") / "latest.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
