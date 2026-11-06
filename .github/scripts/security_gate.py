#!/usr/bin/env python3
"""Summarize security artifacts and optionally enforce a gate.

Default mode is ``report`` so the workflow never blocks a pull request while
the baseline is being triaged. Set the repository variable ``SECURITY_GATE`` to
``block`` to fail whenever secrets or dependency vulnerabilities are present.
SAST and container artifacts are collected for review but do not affect the gate.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

RESULTS = Path("security-results")


def load(name: str):
    path = RESULTS / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def count_secrets() -> int:
    data = load("gitleaks.json")
    return len(data) if isinstance(data, list) else 0


def count_python_vulns() -> int:
    data = load("pip-audit.json")
    if not isinstance(data, dict):
        return 0
    return sum(len(dep.get("vulns") or []) for dep in data.get("dependencies") or [])


def count_node_high() -> int:
    total = 0
    for name in ("pnpm-audit.json", "npm-audit.json"):
        data = load(name)
        if not isinstance(data, dict):
            continue
        metadata = (data.get("metadata") or {}).get("vulnerabilities") or {}
        if metadata:
            total += int(metadata.get("high", 0)) + int(metadata.get("critical", 0))
            continue
        vulns = data.get("vulnerabilities") or {}
        if isinstance(vulns, dict):
            total += sum(
                1 for item in vulns.values()
                if isinstance(item, dict) and item.get("severity") in ("high", "critical")
            )
    return total


def main() -> int:
    mode = os.environ.get("SECURITY_GATE", "report").strip() or "report"
    for name in ("gitleaks.json", "pip-audit.json"):
        if not (RESULTS / name).exists():
            print(f"::warning::security artifact missing: {name}")
    if not any((RESULTS / name).exists()
               for name in ("pnpm-audit.json", "npm-audit.json", "g2-ssr-npm-audit.json")):
        print("::warning::security artifact missing: node audit json")
    counts = {
        "secrets": count_secrets(),
        "python_vulnerabilities": count_python_vulns(),
        "node_high_or_critical": count_node_high(),
    }
    summary = "\n".join(f"- {key}: {value}" for key, value in counts.items())
    print(summary)
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write("## Security scan summary\n\n")
            handle.write(summary + "\n\n")
            handle.write(f"Gate mode: `{mode}`\n")

    if mode == "report":
        return 0
    failures = [key for key, value in counts.items() if value]
    if failures:
        print(f"::error::security gate ({mode}) failed: {', '.join(failures)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
