from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import textwrap
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_CODEX_CONFIG = Path.home() / ".codex" / "config.toml"
DEFAULT_MEMORY_HOME = Path.home() / ".memory"
DEFAULT_CODEX_LOG_ROOT = (
    Path.home()
    / "AppData"
    / "Local"
    / "Packages"
    / "OpenAI.Codex_2p2nqsd0c76g0"
    / "LocalCache"
    / "Local"
    / "Codex"
    / "Logs"
)
DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
REQUIRED_OLLAMA_MODEL = "nomic-embed-text"


@dataclass(slots=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def load_codex_config(path: Path = DEFAULT_CODEX_CONFIG) -> dict[str, Any]:
    if not path.exists():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def parse_simple_yaml(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    data: dict[str, dict[str, str]] = {}
    current_section: str | None = None
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith(" ") and stripped.endswith(":"):
            current_section = stripped[:-1]
            data[current_section] = {}
            continue
        if current_section and ":" in stripped:
            key, value = stripped.split(":", 1)
            data[current_section][key.strip()] = value.strip()
    return data


def request_json(url: str, timeout: float = 5.0) -> tuple[bool, Any]:
    try:
        with urlopen(Request(url), timeout=timeout) as response:
            return True, json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return False, repr(exc)


def run_process(
    args: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 45,
) -> ProcessResult:
    completed = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return ProcessResult(
        returncode=completed.returncode,
        stdout=completed.stdout.strip(),
        stderr=completed.stderr.strip(),
    )


def collect_latest_logs(
    log_root: Path = DEFAULT_CODEX_LOG_ROOT, limit: int = 5
) -> list[dict[str, Any]]:
    if not log_root.exists():
        return []
    files = [path for path in log_root.rglob("*.log") if path.is_file()]
    files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    latest: list[dict[str, Any]] = []
    for path in files[:limit]:
        stat = path.stat()
        latest.append(
            {
                "path": str(path),
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
            }
        )
    return latest


def inspect_configured_servers(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    servers = config.get("mcp_servers", {})
    inspected: dict[str, dict[str, Any]] = {}
    for name, spec in servers.items():
        entry: dict[str, Any] = {
            "kind": "remote" if "url" in spec else "local",
            "configured": True,
        }
        if "command" in spec:
            command_path = Path(spec["command"])
            entry["command"] = spec["command"]
            entry["command_exists"] = command_path.exists()
        if "cwd" in spec:
            entry["cwd"] = spec["cwd"]
            entry["cwd_exists"] = Path(spec["cwd"]).exists()
        if "args" in spec:
            entry["args"] = list(spec["args"])
        if "url" in spec:
            entry["url"] = spec["url"]
        if "bearer_token_env_var" in spec:
            env_name = spec["bearer_token_env_var"]
            entry["bearer_token_env_var"] = env_name
            entry["auth_env_present"] = bool(os.environ.get(env_name))
        inspected[name] = entry
    return inspected


def probe_ollama(
    base_url: str = DEFAULT_OLLAMA_BASE_URL,
    required_model: str = REQUIRED_OLLAMA_MODEL,
) -> dict[str, Any]:
    ok, payload = request_json(f"{base_url}/api/tags")
    result: dict[str, Any] = {
        "base_url": base_url,
        "api_ok": ok,
        "required_model": required_model,
    }
    if ok:
        models = [item.get("name", "") for item in payload.get("models", [])]
        result["models"] = models
        result["required_model_present"] = any(
            model == required_model or model.startswith(f"{required_model}:") for model in models
        )
    else:
        result["error"] = payload
        result["models"] = []
        result["required_model_present"] = False
    return result


def probe_memory_cli(
    memory_exe: Path,
    *,
    project_name: str,
    memory_home: Path | None = None,
    title_prefix: str = "health-probe",
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="caf-mcp-health-") as temp_root:
        cwd = Path(temp_root) / project_name
        cwd.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        if memory_home is not None:
            env["MEMORY_HOME"] = str(memory_home)
        title = f"{title_prefix}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}"
        save = run_process(
            [
                str(memory_exe),
                "save",
                "--title",
                title,
                "--what",
                "automated MCP runtime health probe",
                "--category",
                "context",
                "--tags",
                "healthcheck,mcp",
            ],
            cwd=cwd,
            env=env,
        )
        search = run_process(
            [str(memory_exe), "search", title, "--limit", "1", "--project"],
            cwd=cwd,
            env=env,
        )
        return {
            "project_name": project_name,
            "title": title,
            "save": {
                "returncode": save.returncode,
                "stdout": save.stdout,
                "stderr": save.stderr,
            },
            "search": {
                "returncode": search.returncode,
                "stdout": search.stdout,
                "stderr": search.stderr,
            },
            "memory_home": str(memory_home) if memory_home else str(DEFAULT_MEMORY_HOME),
        }


def build_degraded_memory_home(base_dir: Path, base_url: str = "http://127.0.0.1:9") -> Path:
    memory_home = base_dir / "memory-home"
    memory_home.mkdir(parents=True, exist_ok=True)
    config_text = textwrap.dedent(
        f"""\
        embedding:
          provider: ollama
          model: {REQUIRED_OLLAMA_MODEL}
          base_url: {base_url}

        context:
          semantic: auto
          topup_recent: true
        """
    )
    (memory_home / "config.yaml").write_text(config_text, encoding="utf-8")
    return memory_home


def probe_echovault(
    *,
    memory_exe: Path,
    memory_home: Path = DEFAULT_MEMORY_HOME,
) -> dict[str, Any]:
    config = parse_simple_yaml(memory_home / "config.yaml")
    real_home_probe = probe_memory_cli(
        memory_exe,
        project_name="MCPHealthcheck",
        memory_home=memory_home,
        title_prefix="healthy-echo",
    )

    with tempfile.TemporaryDirectory(prefix="caf-echovault-degraded-") as temp_root:
        degraded_home = build_degraded_memory_home(Path(temp_root))
        degraded_probe = probe_memory_cli(
            memory_exe,
            project_name="MCPHealthcheck",
            memory_home=degraded_home,
            title_prefix="degraded-echo",
        )

    healthy_ok = (
        real_home_probe["save"]["returncode"] == 0 and real_home_probe["search"]["returncode"] == 0
    )
    degraded_ok = (
        degraded_probe["save"]["returncode"] == 0 and degraded_probe["search"]["returncode"] == 0
    )
    degraded_warning = degraded_probe["save"]["stderr"]

    return {
        "memory_exe": str(memory_exe),
        "memory_exe_exists": memory_exe.exists(),
        "memory_home": str(memory_home),
        "memory_home_exists": memory_home.exists(),
        "config": config,
        "healthy_probe": real_home_probe,
        "degraded_probe": degraded_probe,
        "healthy_save_ok": healthy_ok,
        "degraded_save_ok": degraded_ok,
        "degraded_embedding_nonfatal": "Memory saved without vector" in degraded_warning,
    }


def probe_vector_memory() -> dict[str, Any]:
    db_path = DEFAULT_MEMORY_HOME / "vector-memory" / "memory" / "vector_memory.db"
    return {
        "db_path": str(db_path),
        "db_exists": db_path.exists(),
        "db_size_bytes": db_path.stat().st_size if db_path.exists() else 0,
    }


def build_health_report(
    *,
    config_path: Path = DEFAULT_CODEX_CONFIG,
    memory_home: Path = DEFAULT_MEMORY_HOME,
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL,
    required_model: str = REQUIRED_OLLAMA_MODEL,
) -> dict[str, Any]:
    config = load_codex_config(config_path)
    servers = inspect_configured_servers(config)
    echovault_entry = servers.get("echovault", {})
    memory_exe = Path(echovault_entry.get("command", "memory.exe"))
    report = {
        "generated_at": utc_now_iso(),
        "codex_config_path": str(config_path),
        "codex_config_exists": config_path.exists(),
        "mcp_servers": servers,
        "ollama": probe_ollama(base_url=ollama_base_url, required_model=required_model),
        "echovault": probe_echovault(memory_exe=memory_exe, memory_home=memory_home),
        "vector_memory": probe_vector_memory(),
        "codex_logs": {
            "log_root": str(DEFAULT_CODEX_LOG_ROOT),
            "log_root_exists": DEFAULT_CODEX_LOG_ROOT.exists(),
            "latest": collect_latest_logs(),
        },
    }
    report["summary"] = summarize_health(report)
    return report


def summarize_health(report: dict[str, Any]) -> list[str]:
    summary: list[str] = []
    ollama = report["ollama"]
    summary.append(
        "Ollama: healthy"
        if ollama["api_ok"] and ollama["required_model_present"]
        else "Ollama: unavailable or required model missing"
    )
    echovault = report["echovault"]
    if echovault["healthy_save_ok"]:
        summary.append("EchoVault save/read: healthy")
    else:
        summary.append("EchoVault save/read: failing in healthy state")
    if echovault["degraded_save_ok"] and echovault["degraded_embedding_nonfatal"]:
        summary.append(
            "EchoVault degraded path: save succeeds without vectors when Ollama is unreachable"
        )
    elif not echovault["degraded_save_ok"]:
        summary.append("EchoVault degraded path: save fails when embeddings are unavailable")
    vector_db = report["vector_memory"]
    summary.append(
        "vector-memory: healthy"
        if vector_db["db_exists"] and vector_db["db_size_bytes"] > 0
        else "vector-memory: db missing"
    )
    log_info = report["codex_logs"]
    summary.append(
        "Codex logs: present"
        if log_info["log_root_exists"] and log_info["latest"]
        else "Codex logs: missing"
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check local MCP runtime prerequisites and durability paths."
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Write the full report to this JSON file.",
    )
    parser.add_argument(
        "--ollama-base-url",
        default=DEFAULT_OLLAMA_BASE_URL,
        help="Base URL for the local Ollama API.",
    )
    args = parser.parse_args(argv)

    report = build_health_report(ollama_base_url=args.ollama_base_url)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print("MCP Runtime Health")
    for line in report["summary"]:
        print(f"- {line}")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
