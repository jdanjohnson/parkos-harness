"""python -m harness.run_public [module:build]  — run public checks, print table, write public_results.json."""
from __future__ import annotations

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    builder = sys.argv[1] if len(sys.argv) > 1 else "candidate.main:build"
    tests = [p for p in (os.path.join(ROOT, "problem", "tests", n) for n in ("test_public_core.py", "test_public_build.py")) if os.path.exists(p)]
    if not tests:
        print("no problem pack loaded")
        return 3
    env = dict(os.environ, PARKOS_BUILDER=builder, PYTHONPATH=ROOT)
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rA", *tests], cwd=ROOT, env=env,
                       capture_output=True, text=True, check=False)
    rows = []
    for line in r.stdout.splitlines():
        if line.startswith(("PASSED", "FAILED")) and "::" in line:
            status, _, rest = line.partition(" ")
            name = rest.split("::")[-1].split("[")[-1].rstrip("]") if "[" in rest else rest.split("::")[-1]
            rows.append((name, status))
    for name, status in rows:
        print(f"  {'✓' if status == 'PASSED' else '✗'} {name}")
    passed = sum(1 for _, s in rows if s == "PASSED")
    print(f"{passed}/{len(rows)} public checks passing")
    with open(os.path.join(ROOT, "public_results.json"), "w", encoding="utf-8") as fh:
        json.dump({"passed": passed, "failed": len(rows) - passed, "checks": dict(rows), "exit_code": r.returncode}, fh, indent=2)
    if r.returncode not in (0, 1):
        print(r.stdout[-2000:], r.stderr[-2000:])
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
