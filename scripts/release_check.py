#!/usr/bin/env python3
"""Pre-release gate: tracked paths, secrets, manifest, imports, requirements, pytest."""
from __future__ import annotations

import ast
import fnmatch
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDE_FILE = ROOT / "release" / "exclude.txt"
ENV_EXAMPLE = ROOT / ".env.example"
PRODUCTION_MANIFEST = ROOT / "release" / "production_manifest.txt"

SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("openai/azure api key material", re.compile(r"\b[A-Za-z0-9]{32,}\b")),
    ("sk- token", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("codiv/jev key", re.compile(r"\bsk-codiv-[A-Za-z0-9_-]+\b", re.I)),
    ("bearer token", re.compile(r"\bBearer\s+[A-Za-z0-9._-]{20,}\b", re.I)),
    ("jdbc/sql password in URL", re.compile(r"(?i)(PWD|Password)\s*=\s*[^;\s&]{8,}")),
    (
        "azure storage key",
        re.compile(r"(?i)(DefaultEndpointsProtocol|AccountKey)\s*=\s*[A-Za-z0-9+/=]{20,}"),
    ),
]

PLACEHOLDER_VALUE = re.compile(
    r"^(\s*|"
    r".*(YOUR|CHANGE_ME|CHANGEME|EXAMPLE|placeholder|<[^>]+>|\.\.\.).*)$",
    re.I,
)

SENSITIVE_ENV_KEYS = re.compile(
    r"(KEY|SECRET|PASSWORD|TOKEN|CONNECTION_STRING|ADMIN_KEY)$",
    re.I,
)

SCAN_SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".parquet", ".db"}
SCAN_SKIP_GLOBS = ["artifacts/**", "**/__pycache__/**", ".venv/**", ".loop/**"]

# top-level import name → PyPI distribution name in requirements.txt
IMPORT_TO_DIST: dict[str, str] = {
    "yaml": "PyYAML",
    "dotenv": "python-dotenv",
    "azure": "azure-identity",
    "autogen": "pyautogen",
    "sqlalchemy": "sqlalchemy",
    "pandas": "pandas",
    "tiktoken": "tiktoken",
    "graphrag": "graphrag",
    "lancedb": "lancedb",
    "openai": "openai",
    "pyarrow": "pyarrow",
    "numpy": "numpy",
    "duckdb": "duckdb",
    "scipy": "scipy",
    "aiohttp": "aiohttp",
    "tqdm": "tqdm",
    "streamlit": "streamlit",
    "uvicorn": "uvicorn",
    "httpx": "httpx",
    "sqlglot": "sqlglot",
    "pyodbc": "pyodbc",
}

LOCAL_TOPLEVEL = {
    "API_unified",
    "agent_runner",
    "answer_template",
    "aurix_core",
    "both_answer",
    "catalog_runtime",
    "config",
    "data_profile",
    "dual_route",
    "empty_answer_eval",
    "flow_conformance",
    "gate_inputs",
    "graph_config",
    "i05_asyncio_filter",
    "insight_prompt",
    "jev_client",
    "jev_trace",
    "llm_telemetry",
    "main",
    "metadata",
    "odbc_driver",
    "orchestrator",
    "pipeline_response",
    "pii_output",
    "question_time",
    "rai_route_heuristic",
    "request_context",
    "request_state",
    "routing_s4",
    "safety_gate",
    "schema_linker",
    "sql_catalog",
    "sql_column_validate",
    "sql_execute_step",
    "sql_generator_prompt",
    "sql_match_count",
    "sql_pipeline",
    "sql_repair_recovery",
    "sql_safety",
    "sqlglot_validate",
    "azure_health",
    "azure_credential",
    "azure_llm_runtime",
    "azure_openai_endpoint",
}


def _git_ls_files() -> list[str]:
    r = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if r.returncode != 0:
        print("FAIL: git ls-files failed (not a git repo?)", file=sys.stderr)
        sys.exit(2)
    raw = r.stdout.decode("utf-8", errors="replace")
    return [p for p in raw.split("\0") if p]


def _load_exclude_patterns() -> list[str]:
    if not EXCLUDE_FILE.is_file():
        print(f"FAIL: missing {EXCLUDE_FILE.relative_to(ROOT)}", file=sys.stderr)
        sys.exit(2)
    patterns: list[str] = []
    for line in EXCLUDE_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line.replace("\\", "/"))
    return patterns


def _load_production_manifest() -> list[str]:
    if not PRODUCTION_MANIFEST.is_file():
        return []
    paths: list[str] = []
    for line in PRODUCTION_MANIFEST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        paths.append(line.replace("\\", "/"))
    return paths


def _path_matches_exclude(path: str, patterns: list[str]) -> str | None:
    norm = path.replace("\\", "/")
    base = os.path.basename(norm)
    for pat in patterns:
        if pat.endswith("/"):
            prefix = pat.rstrip("/")
            if norm == prefix or norm.startswith(prefix + "/"):
                return pat
        elif "*" in pat or "?" in pat or "**/" in pat:
            if fnmatch.fnmatch(norm, pat) or fnmatch.fnmatch(base, pat):
                return pat
            parts = pat.split("/")
            for i in range(len(parts)):
                sub = "/".join(parts[i:])
                if fnmatch.fnmatch(norm, sub) or fnmatch.fnmatch(base, sub):
                    return pat
        elif norm == pat or norm.startswith(pat + "/"):
            return pat
    return None


def _should_scan_file(path: str) -> bool:
    p = Path(path)
    if p.suffix.lower() in SCAN_SKIP_SUFFIXES:
        return False
    norm = path.replace("\\", "/")
    for g in SCAN_SKIP_GLOBS:
        if fnmatch.fnmatch(norm, g):
            return False
    try:
        data = (ROOT / path).read_bytes()
    except OSError:
        return False
    if b"\x00" in data[:8192]:
        return False
    return True


def _check_tracked_excludes(paths: list[str], patterns: list[str]) -> list[str]:
    bad: list[str] = []
    for path in paths:
        hit = _path_matches_exclude(path, patterns)
        if hit:
            bad.append(f"{path}  (matched exclude: {hit})")
    return bad


def _line_looks_like_code_reference(line: str) -> bool:
    low = line.lower()
    if "_env(" in low or "getenv" in low or "environ" in low or "os.getenv" in low:
        return True
    if "f\"" in line or "f'" in line or "{password}" in low or "{pwd}" in low:
        return True
    if re.match(r"^\s*password\s*=\s*AZURE_", line, re.I):
        return True
    if "AZURE_SQL_PASSWORD" in line and "=" in line:
        return True
    return False


def _check_secrets(paths: list[str]) -> list[str]:
    findings: list[str] = []
    for path in paths:
        if path == ".env.example":
            continue
        if not _should_scan_file(path):
            continue
        try:
            lines = (ROOT / path).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for lineno, line in enumerate(lines, 1):
            if _line_looks_like_code_reference(line):
                continue
            for label, rx in SECRET_PATTERNS:
                if not rx.search(line):
                    continue
                snippet = rx.search(line).group(0)  # type: ignore[union-attr]
                if "YOUR-" in snippet or "CHANGE" in snippet.upper():
                    continue
                if label == "openai/azure api key material" and len(snippet) < 40:
                    continue
                if "example" in path.lower() or path.startswith("tests/"):
                    if len(snippet) < 48:
                        continue
                findings.append(f"{path}:{lineno}: possible {label}")
                break
    return findings


def _check_env_example() -> list[str]:
    if not ENV_EXAMPLE.is_file():
        return ["missing .env.example"]
    issues: list[str] = []
    for lineno, raw in enumerate(ENV_EXAMPLE.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not SENSITIVE_ENV_KEYS.search(key):
            continue
        if PLACEHOLDER_VALUE.match(value):
            continue
        if value and len(value) >= 16:
            issues.append(
                f".env.example:{lineno} {key}= looks like a real value (use empty or YOUR-… placeholder)"
            )
    return issues


def _check_manifest_files_exist(manifest: list[str]) -> list[str]:
    missing: list[str] = []
    for rel in manifest:
        if not (ROOT / rel).is_file():
            missing.append(rel)
    return missing


def _imports_in_file(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        return [f"__syntax__:{exc}"]
    mods: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.append(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mods.append(node.module.split(".")[0])
            else:
                for alias in node.names:
                    if alias.name != "*":
                        mods.append(alias.name.split(".")[0])
    return mods


def _check_production_imports(manifest: list[str], patterns: list[str]) -> list[str]:
    bad: list[str] = []
    for rel in manifest:
        if not rel.endswith(".py"):
            continue
        path = ROOT / rel
        if not path.is_file():
            continue
        for mod in _imports_in_file(path):
            if mod.startswith("__syntax__"):
                bad.append(f"{rel}: {mod}")
                continue
            if mod in LOCAL_TOPLEVEL:
                target = f"{mod}.py"
                hit = _path_matches_exclude(target, patterns)
                if hit:
                    bad.append(f"{rel} imports local `{mod}` (excluded dev path: {hit})")
                continue
            if mod == "scripts":
                bad.append(f"{rel} imports `scripts` (DEV-ONLY)")
            elif mod == "eval":
                bad.append(f"{rel} imports `eval` (TEST harness)")
            elif mod == "ISSUES":
                bad.append(f"{rel} imports ISSUES (DEV-ONLY)")
    return bad


def _parse_requirements() -> set[str]:
    pkgs: set[str] = set()
    if not (ROOT / "requirements.txt").is_file():
        return pkgs
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = re.split(r"[<>=!\[]", line, maxsplit=1)[0].strip()
        if name:
            pkgs.add(name.lower())
    return pkgs


def _third_party_imports_in_production(manifest: list[str]) -> set[str]:
    needed: set[str] = set()
    for rel in manifest:
        if not rel.endswith(".py"):
            continue
        path = ROOT / rel
        if not path.is_file():
            continue
        for mod in _imports_in_file(path):
            if mod.startswith("__syntax__"):
                continue
            if mod in LOCAL_TOPLEVEL or mod in sys.stdlib_module_names:
                continue
            dist = IMPORT_TO_DIST.get(mod, mod)
            needed.add(dist)
    return needed


def _check_requirements(manifest: list[str]) -> list[str]:
    reqs = _parse_requirements()
    needed = _third_party_imports_in_production(manifest)
    missing = sorted(d for d in needed if d.lower() not in reqs)
    return missing


def _run_pytest_non_live(cwd: Path) -> tuple[bool, str]:
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "tests/",
        "-q",
        "-m",
        "not live and not groupchat_legacy",
    ]
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    tail = (r.stdout + r.stderr).strip()[-4000:]
    return r.returncode == 0, tail


def _worktree_smoke() -> list[str]:
    errors: list[str] = []
    wt_dir = Path(tempfile.mkdtemp(prefix="aurix-release-wt-"))
    try:
        add = subprocess.run(
            ["git", "worktree", "add", "--detach", str(wt_dir), "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if add.returncode != 0:
            return [f"git worktree add failed: {add.stderr.strip()[-500:]}"]

        manifest = _load_production_manifest()
        for rel in manifest:
            src = ROOT / rel
            if src.is_file():
                dest = wt_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)

        imp = subprocess.run(
            [sys.executable, "-c", "import aurix_core, main"],
            cwd=wt_dir,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": str(wt_dir)},
        )
        if imp.returncode != 0:
            errors.append("worktree import aurix_core, main failed:")
            errors.append((imp.stderr or imp.stdout).strip()[-2000:])

        ok, tail = _run_pytest_non_live(wt_dir)
        if not ok:
            errors.append("worktree pytest -m 'not live' failed (tail):")
            errors.append(tail or "(no output)")
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(wt_dir)],
            cwd=ROOT,
            capture_output=True,
        )
        if wt_dir.exists():
            shutil.rmtree(wt_dir, ignore_errors=True)
    return errors


def main() -> int:
    print("release_check: root", ROOT)
    patterns = _load_exclude_patterns()
    manifest = _load_production_manifest()
    tracked = _git_ls_files()

    failures: list[str] = []

    excl = _check_tracked_excludes(tracked, patterns)
    if excl:
        failures.append("Tracked files match release/exclude.txt:")
        failures.extend(f"  - {x}" for x in excl[:50])
        if len(excl) > 50:
            failures.append(f"  ... and {len(excl) - 50} more")

    secrets = _check_secrets(tracked)
    if secrets:
        failures.append("Possible secrets in tracked files:")
        failures.extend(f"  - {x}" for x in secrets[:30])

    env_issues = _check_env_example()
    if env_issues:
        failures.append(".env.example issues:")
        failures.extend(f"  - {x}" for x in env_issues)

    missing_prod = _check_manifest_files_exist(manifest)
    if missing_prod:
        failures.append("production_manifest.txt paths missing on disk:")
        failures.extend(f"  - {x}" for x in missing_prod)

    imp_bad = _check_production_imports(manifest, patterns)
    if imp_bad:
        failures.append("Production imports DEV-ONLY modules:")
        failures.extend(f"  - {x}" for x in imp_bad)

    req_missing = _check_requirements(manifest)
    if req_missing:
        failures.append("requirements.txt missing packages used by production code:")
        failures.extend(f"  - {x}" for x in req_missing)

    ok, pytest_log = _run_pytest_non_live(ROOT)
    if not ok:
        failures.append("pytest tests/ -q -m 'not live' failed (tail):")
        failures.append(pytest_log or "(no output)")

    wt = _worktree_smoke()
    if wt:
        failures.append("clean worktree smoke:")
        failures.extend(f"  {line}" for line in wt)

    if failures:
        print("RELEASE CHECK FAILED", file=sys.stderr)
        for line in failures:
            print(line, file=sys.stderr)
        return 1

    print("RELEASE CHECK PASSED")
    print("  tracked paths:", len(tracked))
    print("  production manifest:", len(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())