from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from openevolve import OpenEvolve  # type: ignore[import-untyped]
from openevolve.config import LLMModelConfig, load_config  # type: ignore[import-untyped]
from openevolve.llm.base import LLMInterface  # type: ignore[import-untyped]


class CodexCliLlm(LLMInterface):  # type: ignore[misc]
    """Read-only OpenEvolve model client backed by the authenticated Codex CLI."""

    def __init__(self, config: LLMModelConfig):
        executable = shutil.which("codex")
        if executable is None:
            raise RuntimeError("codex CLI is not available on PATH")
        self.executable = executable
        self.model = config.name
        self.timeout = int(config.timeout or 180)

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        return await self._call(prompt)

    async def generate_with_context(
        self, system_message: str, messages: list[dict[str, str]], **kwargs: Any
    ) -> str:
        conversation = "\n\n".join(
            f"{message.get('role', 'user').upper()}: {message.get('content', '')}"
            for message in messages
        )
        prompt = f"SYSTEM INSTRUCTIONS:\n{system_message}\n\nCONVERSATION:\n{conversation}"
        return await self._call(prompt)

    async def _call(self, prompt: str) -> str:
        with tempfile.TemporaryDirectory(prefix="shaurya-codex-evolve-") as directory:
            output = Path(directory) / "response.txt"
            process = await asyncio.create_subprocess_exec(
                self.executable,
                "exec",
                "--ephemeral",
                "--ignore-user-config",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "--model",
                self.model,
                "--cd",
                directory,
                "--output-last-message",
                str(output),
                "-",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, stderr = await asyncio.wait_for(
                    process.communicate(prompt.encode("utf-8")), timeout=self.timeout
                )
            except TimeoutError:
                process.kill()
                await process.wait()
                raise RuntimeError(f"Codex CLI timed out after {self.timeout}s") from None
            if process.returncode != 0:
                error = stderr.decode("utf-8", errors="replace")[-2_000:]
                raise RuntimeError(f"Codex CLI failed with {process.returncode}: {error}")
            if not output.exists():
                raise RuntimeError("Codex CLI returned no final response")
            return output.read_text(encoding="utf-8")


def _client(config: LLMModelConfig) -> CodexCliLlm:
    return CodexCliLlm(config)


async def _run(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    configured: set[int] = set()
    for model in [*config.llm.models, *config.llm.evaluator_models]:
        if id(model) not in configured:
            model.init_client = _client
            configured.add(id(model))
    evolution = OpenEvolve(
        initial_program_path=str(args.initial_program),
        evaluation_file=str(args.evaluator),
        config=config,
        output_dir=str(args.output),
    )
    best = await evolution.run(iterations=args.iterations)
    print("Best metrics:")
    for name, value in best.metrics.items():
        print(f"  {name}: {value}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initial-program", type=Path, required=True)
    parser.add_argument("--evaluator", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=20)
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
