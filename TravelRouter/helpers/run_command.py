import asyncio
import re
import shlex
import subprocess
from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel


ResultType = TypeVar("ResultType")


class CmdStatus(BaseModel):
    """
    Default is error
    """
    success: bool = False
    stdout: str = ""
    stderr: str = ""
    command: str = ""


def run_command(command: list[str], timeout: int = 20) -> CmdStatus:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError:
        return CmdStatus(
            stderr=f"Missing command: {command[0]}",
            command=" ".join(shlex.quote(part) for part in command)
        )
    except subprocess.TimeoutExpired:
        return CmdStatus(
            stderr="Command timed out",
            command=" ".join(shlex.quote(part) for part in command)
        )

    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()

    return CmdStatus(
        success=completed.returncode == 0 and not stderr,
        stdout=stdout,
        stderr=stderr,
        command=" ".join(shlex.quote(part) for part in command)
    )


async def run_in_thread(
    func: Callable[..., ResultType],
    *args,
    **kwargs,
) -> ResultType:
    return await asyncio.to_thread(func, *args, **kwargs)
