"""Isolated code execution in a throwaway Docker container.

Isolation: no network (``--network none``), read-only root filesystem, a private writable
copy of the project's code artifacts mounted at /workspace (nothing else from the host),
non-root user, all capabilities dropped, no-new-privileges, CPU/memory/pid limits and a
hard wall-clock timeout. No credentials or environment from the host are passed in.
If Docker or the sandbox image is unavailable, execution tools are disabled - there is no
fallback to running code on the host.
"""
from __future__ import annotations

import asyncio
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ..config import settings

MAX_OUTPUT = 20_000


@dataclass
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    duration_s: float


class SandboxUnavailable(RuntimeError):
    pass


_status_cache: dict[str, object] = {}


async def _run(*args: str, timeout: float = 15) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, "", "timeout"
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


async def status(refresh: bool = False) -> dict:
    if _status_cache and not refresh:
        return dict(_status_cache)
    result = {"available": False, "reason": "", "image": settings.sandbox_image}
    if shutil.which("docker") is None:
        result["reason"] = "Docker is not installed."
    else:
        code, _, err = await _run("docker", "info", "--format", "{{.ServerVersion}}")
        if code != 0:
            result["reason"] = "Docker is installed but the daemon is not running."
        else:
            code, _, _ = await _run("docker", "image", "inspect", settings.sandbox_image)
            if code != 0:
                result["reason"] = (f"Sandbox image {settings.sandbox_image} is not built. "
                                    "Run: docker compose --profile build-only build sandbox-image")
            else:
                result["available"] = True
    _status_cache.clear()
    _status_cache.update(result)
    return result


def safe_rel_path(p: str) -> PurePosixPath:
    pp = PurePosixPath(p.strip().lstrip("/"))
    if not pp.parts or any(part in ("..", "") for part in pp.parts) or pp.is_absolute():
        raise ValueError(f"Invalid file path: {p}")
    return pp


async def execute(files: dict[str, str], command: list[str], timeout_s: int = 60) -> SandboxResult:
    st = await status()
    if not st["available"]:
        raise SandboxUnavailable(st["reason"])
    work = settings.sandbox_dir / uuid.uuid4().hex
    work.mkdir(parents=True, exist_ok=True)
    try:
        for rel, content in files.items():
            target = work / Path(*safe_rel_path(rel).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        work.chmod(0o777)
        for p in work.rglob("*"):
            p.chmod(0o777 if p.is_dir() else 0o666)
        name = f"agentoffice-sbx-{uuid.uuid4().hex[:12]}"
        args = [
            "docker", "run", "--rm", "--name", name,
            "--network", "none",
            "--read-only", "--tmpfs", "/tmp:rw,size=64m",
            "--memory", "512m", "--memory-swap", "512m", "--cpus", "1", "--pids-limit", "128",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--user", "10001:10001",
            "-e", "HOME=/tmp", "-e", "PYTHONDONTWRITEBYTECODE=1",
            "-v", f"{work}:/workspace:rw", "-w", "/workspace",
            settings.sandbox_image, *command,
        ]
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        timed_out = False
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except asyncio.TimeoutError:
            timed_out = True
            await _run("docker", "kill", name, timeout=10)
            out, err = await proc.communicate()
        return SandboxResult(
            exit_code=proc.returncode if proc.returncode is not None else -1,
            stdout=out.decode(errors="replace")[-MAX_OUTPUT:],
            stderr=err.decode(errors="replace")[-MAX_OUTPUT:],
            timed_out=timed_out,
            duration_s=round(loop.time() - t0, 2),
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)
