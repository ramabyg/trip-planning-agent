"""Pre-commit verification: import sanity + unit tests (and optionally more).

Usage:
    python scripts/run_checks.py                # import check + offline unit tests
    python scripts/run_checks.py --integration  # additionally run live API tests
    python scripts/run_checks.py --all          # everything

Wired as the git pre-commit hook via .githooks/pre-commit.
Exits non-zero on the first failing stage.
"""
import argparse
import importlib
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MODULES_TO_IMPORT = ["schemas", "maps_client", "tools", "agent"]


def check_imports() -> bool:
    print("=== Stage 1: import sanity ===")
    sys.path.insert(0, REPO_ROOT)
    ok = True
    for module_name in MODULES_TO_IMPORT:
        try:
            importlib.import_module(module_name)
            print(f"  OK   {module_name}")
        except Exception as e:
            print(f"  FAIL {module_name}: {e}")
            ok = False
    return ok


def run_pytest(marker_expr: str, label: str) -> bool:
    print(f"=== Stage 2: {label} ===")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-m", marker_expr, "-q"],
        cwd=REPO_ROOT,
    )
    return result.returncode in (0, 5)  # 5 = no tests collected (all skipped)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--integration", action="store_true",
                        help="also run live API tests (needs MAPS_API_KEY / NPS_API_KEY)")
    parser.add_argument("--all", action="store_true", help="run everything")
    args = parser.parse_args()

    if not check_imports():
        print("\nFAILED: import sanity check")
        return 1

    if not run_pytest("not integration", "offline unit tests"):
        print("\nFAILED: unit tests")
        return 1

    if args.integration or args.all:
        if not run_pytest("integration", "live integration tests"):
            print("\nFAILED: integration tests")
            return 1

    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
