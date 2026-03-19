#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import socket
import sqlite3
import subprocess
import tempfile
import textwrap
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CODEX_CONFIG = Path(r"C:\Users\MySQL\.codex\config.toml")
CODEX_LOG_ROOT = Path(
    r"C:\Users\MySQL\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0"
    r"\LocalCache\Local\Codex\Logs"
)
OLLAMA_URL = "http://127.0.0.1:11434/api/tags"
OLLAMA_MODEL = "nomic-embed-text"


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _run_command(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }
    except Exception as exc:  # pragma: no cover - defensive probe wrapper
        return {
            "ok": False,
            "returncode": None,
            "stdout": "",
            "stderr": repr(exc),
        }


def _probe_executable(path_str: str | None) -> dict[str, Any]:
    path = Path(path_str) if path_str else None
    return {
        "path": str(path) if path else None,
        "exists": bool(path and path.exists()),
    }


def _status(ok: bool, summary: str, **details: Any) -> dict[str, Any]:
    data = {"ok": ok, "summary": summary}
    data.update(details)
    return data


def _load_config() -> dict[str, Any]:
    config_text = CODEX_CONFIG.read_text(encoding="utf-8")
    return tomllib.loads(config_text)


def _probe_ollama() -> dict[str, Any]:
    tcp_open = False
    sock = socket.socket()
    sock.settimeout(2)
    try:
        sock.connect(("127.0.0.1", 11434))
        tcp_open = True
    except OSError:
        tcp_open = False
    finally:
        sock.close()

    try:
        request = Request(OLLAMA_URL)
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        models = [model.get("name", "") for model in payload.get("models", [])]
        wanted = any(name.startswith(f"{OLLAMA_MODEL}:") or name == OLLAMA_MODEL for name in models)
        return _status(
            tcp_open and wanted,
            "Ollama API reachable" if tcp_open else "Ollama API unreachable",
            tcp_open=tcp_open,
            api_ok=True,
            models=models,
            required_model_present=wanted,
        )
    except URLError as exc:
        return _status(
            False,
            "Ollama API probe failed",
            tcp_open=tcp_open,
            api_ok=False,
            error=repr(exc),
            models=[],
            required_model_present=False,
        )
    except Exception as exc:  # pragma: no cover - defensive
        return _status(
            False,
            "Ollama API probe failed",
            tcp_open=tcp_open,
            api_ok=False,
            error=repr(exc),
            models=[],
            required_model_present=False,
        )


def _probe_echovault_read(memory_exe: Path) -> dict[str, Any]:
    result = _run_command(
        [
            str(memory_exe),
            "context",
            "--limit",
            "1",
            "--fts-only",
            "--query",
            "CiscoAutoFlash",
        ],
        cwd=PROJECT_ROOT,
        timeout=30,
    )
    return _status(
        result["ok"],
        "EchoVault read probe succeeded" if result["ok"] else "EchoVault read probe failed",
        command=[
            str(memory_exe),
            "context",
            "--limit",
            "1",
            "--fts-only",
            "--query",
            "CiscoAutoFlash",
        ],
        stdout=result["stdout"][:1200],
        stderr=result["stderr"][:1200],
        returncode=result["returncode"],
    )


def _probe_echovault_save(memory_exe: Path, *, degraded: bool = False) -> dict[str, Any]:
    if degraded:
        temp_home = Path(tempfile.mkdtemp(prefix="echovault_probe_"))
        (temp_home / "vault").mkdir(parents=True, exist_ok=True)
        (temp_home / "config.yaml").write_text(
            textwrap.dedent(
                """
                embedding:
                  provider: ollama
                  model: nomic-embed-text
                  base_url: http://127.0.0.1:9
                context:
                  semantic: auto
                  topup_recent: true
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        env = dict(os.environ)
        env["MEMORY_HOME"] = str(temp_home)
        project = "MCPHealthDegraded"
        title = f"EchoVault degraded save probe {_iso_now()}"
    else:
        env = dict(os.environ)
        project = "MCPHealth"
        title = f"EchoVault healthy save probe {_iso_now()}"

    result = _run_command(
        [
            str(memory_exe),
            "save",
            "--title",
            title,
            "--what",
            "Automated MCP runtime health-check save probe.",
            "--why",
            "Confirms that EchoVault writes are currently durable from the installed CLI path.",
            "--impact",
            (
                "Used to decide whether EchoVault can be trusted as the primary durable "
                "memory backend."
            ),
            "--tags",
            "mcp,echovault,healthcheck,auto-generated",
            "--category",
            "context",
            "--project",
            project,
        ],
        cwd=PROJECT_ROOT,
        env=env,
        timeout=40,
    )
    stderr = result["stderr"][:1200]
    if degraded:
        ok = result["ok"] and "Memory saved without vector" in stderr
        summary = (
            "EchoVault degraded save probe succeeded without vectors"
            if ok
            else "EchoVault degraded save probe failed"
        )
    else:
        ok = result["ok"]
        summary = (
            "EchoVault healthy save probe succeeded"
            if ok
            else "EchoVault healthy save probe failed"
        )
    return _status(
        ok,
        summary,
        degraded=degraded,
        command=result.get("command"),
        stdout=result["stdout"][:1200],
        stderr=stderr,
        returncode=result["returncode"],
    )


def _extract_vector_working_dir(server_cfg: dict[str, Any]) -> Path | None:
    args = server_cfg.get("args", [])
    if "--working-dir" not in args:
        return None
    index = args.index("--working-dir")
    if index + 1 >= len(args):
        return None
    return Path(args[index + 1])


def _probe_vector_memory(server_cfg: dict[str, Any]) -> dict[str, Any]:
    command = Path(server_cfg["command"])
    working_dir = _extract_vector_working_dir(server_cfg)
    db_path = working_dir / "memory" / "vector_memory.db" if working_dir else None
    sqlite_ok = False
    db_error = None
    if db_path and db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
            conn.close()
            sqlite_ok = True
        except sqlite3.Error as exc:
            db_error = repr(exc)
    help_result = _run_command(
        [str(command), "run", server_cfg["args"][1], "--help"],
        cwd=PROJECT_ROOT,
        timeout=30,
    )
    ok = (
        command.exists()
        and bool(working_dir and working_dir.exists())
        and bool(db_path and db_path.exists())
        and sqlite_ok
    )
    return _status(
        ok,
        "vector-memory probe succeeded" if ok else "vector-memory probe failed",
        command_exists=command.exists(),
        working_dir=str(working_dir) if working_dir else None,
        working_dir_exists=bool(working_dir and working_dir.exists()),
        db_path=str(db_path) if db_path else None,
        db_exists=bool(db_path and db_path.exists()),
        sqlite_ok=sqlite_ok,
        sqlite_error=db_error,
        help_returncode=help_result["returncode"],
        help_stderr=help_result["stderr"][:500],
    )


def _probe_tree_sitter(server_cfg: dict[str, Any]) -> dict[str, Any]:
    command = Path(server_cfg["command"])
    args = server_cfg.get("args", [])
    package_spec = args[1] if len(args) > 1 else ""
    log_path = Path(args[4]) if len(args) >= 5 else None
    help_result = _run_command(
        [str(command), "--from", package_spec, "jcodemunch-mcp", "--help"],
        cwd=Path(server_cfg.get("cwd", PROJECT_ROOT)),
        timeout=40,
    )
    ok = command.exists() and help_result["ok"]
    return _status(
        ok,
        "tree-sitter probe succeeded" if ok else "tree-sitter probe failed",
        command_exists=command.exists(),
        package_spec=package_spec,
        log_path=str(log_path) if log_path else None,
        log_exists=bool(log_path and log_path.exists()),
        help_returncode=help_result["returncode"],
        help_stderr=help_result["stderr"][:500],
    )


def _probe_code_graph(server_cfg: dict[str, Any]) -> dict[str, Any]:
    command = Path(server_cfg["command"])
    help_result = _run_command([str(command), "--help"], cwd=PROJECT_ROOT, timeout=20)
    ok = command.exists() and help_result["ok"]
    return _status(
        ok,
        "code-graph probe succeeded" if ok else "code-graph probe failed",
        command_exists=command.exists(),
        help_returncode=help_result["returncode"],
        help_stderr=help_result["stderr"][:500],
    )


def _probe_github_mcp(server_cfg: dict[str, Any]) -> dict[str, Any]:
    token_env = server_cfg.get("bearer_token_env_var")
    token = os.environ.get(token_env, "") if token_env else ""
    gh_path = Path(r"C:\Program Files\GitHub CLI\gh.exe")
    if gh_path.exists():
        gh_result = _run_command(
            [str(gh_path), "auth", "status"],
            cwd=PROJECT_ROOT,
            timeout=20,
        )
    else:
        gh_result = {
            "ok": False,
            "returncode": None,
            "stdout": "",
            "stderr": "gh.exe not found",
        }
    ok = bool(server_cfg.get("url")) and (bool(token) or gh_result["ok"])
    return _status(
        ok,
        "github-mcp prerequisites look healthy" if ok else "github-mcp prerequisites incomplete",
        url=server_cfg.get("url"),
        token_env_var=token_env,
        token_present=bool(token),
        gh_exists=gh_path.exists(),
        gh_auth_ok=gh_result["ok"],
        gh_stderr=gh_result["stderr"][:500],
    )


def _probe_logs() -> dict[str, Any]:
    latest: list[dict[str, Any]] = []
    if CODEX_LOG_ROOT.exists():
        files = sorted(
            CODEX_LOG_ROOT.rglob("codex-desktop-*.log"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for path in files[:6]:
            latest.append(
                {
                    "path": str(path),
                    "size": path.stat().st_size,
                    "modified_at": datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat(),
                }
            )
    return _status(
        CODEX_LOG_ROOT.exists() and bool(latest),
        "Codex log directory present" if CODEX_LOG_ROOT.exists() else "Codex log directory missing",
        log_root=str(CODEX_LOG_ROOT),
        latest_logs=latest,
    )


def _build_report() -> dict[str, Any]:
    config = _load_config()
    servers = config.get("mcp_servers", {})
    echovault_cfg = servers["echovault"]
    vector_cfg = servers["vector-memory"]
    tree_cfg = servers["tree-sitter"]
    code_graph_cfg = servers["code-graph"]
    github_cfg = servers["github-mcp"]

    binary_checks = {
        "echovault": _probe_executable(echovault_cfg.get("command")),
        "vector-memory": _probe_executable(vector_cfg.get("command")),
        "tree-sitter": _probe_executable(tree_cfg.get("command")),
        "code-graph": _probe_executable(code_graph_cfg.get("command")),
        "gh": _probe_executable(r"C:\Program Files\GitHub CLI\gh.exe"),
    }

    memory_exe = Path(echovault_cfg["command"])
    report = {
        "generated_at": _iso_now(),
        "project_root": str(PROJECT_ROOT),
        "config_path": str(CODEX_CONFIG),
        "binary_checks": binary_checks,
        "probes": {
            "ollama": _probe_ollama(),
            "echovault_read": _probe_echovault_read(memory_exe),
            "echovault_save_healthy": _probe_echovault_save(memory_exe, degraded=False),
            "echovault_save_degraded": _probe_echovault_save(memory_exe, degraded=True),
            "vector_memory": _probe_vector_memory(vector_cfg),
            "tree_sitter": _probe_tree_sitter(tree_cfg),
            "code_graph": _probe_code_graph(code_graph_cfg),
            "github_mcp": _probe_github_mcp(github_cfg),
            "codex_logs": _probe_logs(),
        },
    }
    critical_keys = [
        "ollama",
        "echovault_read",
        "echovault_save_healthy",
        "vector_memory",
        "tree_sitter",
        "code_graph",
        "github_mcp",
        "codex_logs",
    ]
    report["overall_ok"] = all(report["probes"][key]["ok"] for key in critical_keys)
    return report


def _format_summary(report: dict[str, Any]) -> str:
    lines = [
        f"overall_ok: {'yes' if report['overall_ok'] else 'no'}",
        f"generated_at: {report['generated_at']}",
    ]
    for name, probe in report["probes"].items():
        lines.append(f"- {name}: {'OK' if probe['ok'] else 'FAIL'} | {probe['summary']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check local MCP runtime prerequisites and durable memory health."
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        help="Write the full machine-readable report to this path.",
    )
    parser.add_argument(
        "--summary-out",
        type=Path,
        help="Write the human summary to this path.",
    )
    parser.add_argument("--json", action="store_true", help="Print only JSON to stdout.")
    args = parser.parse_args()

    report = _build_report()
    summary = _format_summary(report)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if args.summary_out:
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(summary + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(summary)
        if args.json_out:
            print(f"json_report: {args.json_out}")
        if args.summary_out:
            print(f"summary_report: {args.summary_out}")

    return 0 if report["overall_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
