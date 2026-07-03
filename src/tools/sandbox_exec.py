"""Restricted, network-disabled execution of LLM-generated pandas code.

This is the ONLY place in the system that touches the real DataFrame's row-level
data. It never returns raw rows to a caller that forwards them to the LLM — the
result is always reduced to a small, JSON-safe, capped/aggregated summary before
it re-enters graph state (see spec/architecture.md#llm-boundary).

Pure function: `run(code, df) -> {"status", "result_summary", "error"}`. Never
raises — every failure mode (syntax error, forbidden import, runtime error,
timeout) is captured and returned as a structured error.
"""
from __future__ import annotations

import ast
import builtins as _builtins_module
import math
import re
import statistics
import datetime
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutureTimeoutError
from typing import Any

import numpy as np
import pandas as pd

# Imports the generated code is allowed to use. Everything else (os, sys,
# socket, subprocess, requests, urllib, importlib, pathlib, shutil, ...) is
# rejected at the AST-validation stage before any code executes.
ALLOWED_IMPORT_MODULES = {"pandas", "numpy", "math", "statistics", "datetime", "re"}

# Names/attributes that are never allowed to appear in generated code, whether
# as a bare name, an attribute access, or a call target.
FORBIDDEN_NAMES = {
    "os", "sys", "socket", "subprocess", "shutil", "pathlib", "requests",
    "urllib", "http", "importlib", "builtins", "__import__", "eval", "exec",
    "compile", "open", "input", "breakpoint", "globals", "locals", "vars",
    "exit", "quit", "getattr", "setattr", "delattr",
}

MAX_RESULT_ROWS = 20
EXEC_TIMEOUT_SECONDS = 15

_ALLOWED_BUILTIN_NAMES = (
    "abs", "all", "any", "bool", "dict", "enumerate", "filter", "float",
    "int", "len", "list", "map", "max", "min", "print", "range", "repr",
    "reversed", "round", "set", "sorted", "str", "sum", "tuple", "zip",
    "isinstance", "type", "frozenset", "divmod", "pow", "next", "iter",
)
_SAFE_BUILTINS = {
    name: getattr(_builtins_module, name)
    for name in _ALLOWED_BUILTIN_NAMES
    if hasattr(_builtins_module, name)
}


class SandboxSecurityError(Exception):
    """Raised when generated code violates the sandbox's allowlist."""


class _SandboxTimeoutError(Exception):
    """Raised internally when execution exceeds the wall-clock timeout."""


def _validate_ast(code: str) -> ast.Module:
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        raise SandboxSecurityError(f"Syntax error in generated code: {exc}") from exc

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.Import):
                module_roots = [alias.name.split(".")[0] for alias in node.names]
            else:
                module_roots = [node.module.split(".")[0]] if node.module else []
            for root in module_roots:
                if root not in ALLOWED_IMPORT_MODULES:
                    raise SandboxSecurityError(f"Import of module '{root}' is not allowed")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            raise SandboxSecurityError(f"Use of '{node.id}' is not allowed")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__") and node.attr.endswith("__"):
                raise SandboxSecurityError(f"Access to dunder attribute '{node.attr}' is not allowed")
            if node.attr in FORBIDDEN_NAMES:
                raise SandboxSecurityError(f"Access to attribute '{node.attr}' is not allowed")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_NAMES:
                raise SandboxSecurityError(f"Call to '{node.func.id}' is not allowed")

    return tree


def _run_with_timeout(func, timeout_seconds: int) -> None:
    # Thread-based timeout: signal.alarm()/SIGALRM only works in the main
    # thread of the main interpreter, but this is invoked from request-handler
    # threads under uvicorn/FastAPI. Run `func` in a single-worker thread pool
    # and enforce the wall-clock timeout via Future.result(timeout=...) instead.
    # Caveat: Python threads cannot be forcibly killed, so on timeout the
    # worker thread may continue running in the background until it finishes
    # naturally; this is an accepted limitation for this single-user local tool.
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(func)
        try:
            future.result(timeout=timeout_seconds)
        except _FutureTimeoutError as exc:
            raise _SandboxTimeoutError(f"Execution exceeded {timeout_seconds}s timeout") from exc
    finally:
        # wait=False: don't block shutdown on a timed-out worker thread that
        # may still be running (threads can't be force-killed in Python).
        executor.shutdown(wait=False)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if value is pd.NaT:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _summarize_result(result: Any) -> dict:
    """Reduce an arbitrary result value to a small, JSON-safe, capped summary.

    Never returns more than MAX_RESULT_ROWS rows of row-level data; anything
    larger is reduced further via describe()-style aggregation and the summary
    explicitly states it was aggregated.
    """
    if isinstance(result, pd.DataFrame):
        total_rows = len(result)
        if total_rows <= MAX_RESULT_ROWS:
            return {
                "type": "table",
                "row_count": total_rows,
                "aggregated": False,
                "data": _json_safe(result.to_dict(orient="records")),
            }
        described = result.describe(include="all").to_dict()
        return {
            "type": "table_summary",
            "row_count": total_rows,
            "aggregated": True,
            "note": f"Result had {total_rows} rows; too large to return raw, "
                    f"showing an aggregated describe() summary instead.",
            "describe": _json_safe(described),
        }

    if isinstance(result, pd.Series):
        total = len(result)
        if total <= MAX_RESULT_ROWS:
            return {
                "type": "series",
                "row_count": total,
                "aggregated": False,
                "data": _json_safe(result.to_dict()),
            }
        described = result.describe().to_dict()
        return {
            "type": "series_summary",
            "row_count": total,
            "aggregated": True,
            "note": f"Series had {total} values; too large to return raw, "
                    f"showing an aggregated describe() summary instead.",
            "describe": _json_safe(described),
        }

    if isinstance(result, dict):
        total = len(result)
        oversized_value = any(
            isinstance(v, (list, tuple, dict)) and len(v) > MAX_RESULT_ROWS
            for v in result.values()
        )
        if total <= MAX_RESULT_ROWS and not oversized_value:
            return {
                "type": "dict",
                "count": total,
                "aggregated": False,
                "data": _json_safe(result),
            }
        capped_items = {}
        for k, v in list(result.items())[:MAX_RESULT_ROWS]:
            if isinstance(v, (list, tuple, dict)) and len(v) > MAX_RESULT_ROWS:
                v = {
                    "aggregated": True,
                    "count": len(v),
                    "note": "Nested value too large to return raw; showing count only.",
                }
            capped_items[k] = v
        return {
            "type": "dict_summary",
            "count": total,
            "aggregated": True,
            "note": f"Dict had {total} keys or an oversized nested value; too large to "
                    f"return raw, showing a capped/aggregated summary instead.",
            "data": _json_safe(capped_items),
        }

    if isinstance(result, (list, tuple)):
        total = len(result)
        capped = list(result)[:MAX_RESULT_ROWS]
        return {
            "type": "list",
            "count": total,
            "aggregated": total > MAX_RESULT_ROWS,
            "data": _json_safe(capped),
        }

    if isinstance(result, (int, float, bool, str)) or result is None:
        return {"type": "scalar", "data": _json_safe(result)}

    if hasattr(result, "item"):
        return {"type": "scalar", "data": _json_safe(result.item())}

    return {"type": "other", "data": str(result)[:500]}


def run(code: str, df: pd.DataFrame) -> dict:
    """Execute `code` against `df` in a restricted, network-disabled sandbox.

    Convention: the generated code assumes a DataFrame variable `df` is
    already loaded and must assign its answer to a variable named `result`.

    Returns `{"status": "success"|"error", "result_summary": dict|None,
    "error": str|None}`. Never raises.
    """
    try:
        tree = _validate_ast(code)
    except SandboxSecurityError as exc:
        return {"status": "error", "result_summary": None, "error": str(exc)}

    restricted_globals: dict[str, Any] = {
        "__builtins__": _SAFE_BUILTINS,
        "pd": pd,
        "np": np,
        "math": math,
        "statistics": statistics,
        "datetime": datetime,
        "re": re,
    }
    local_vars: dict[str, Any] = {"df": df.copy(deep=True)}

    def _exec() -> None:
        compiled = compile(tree, "<generated_code>", "exec")
        exec(compiled, restricted_globals, local_vars)  # noqa: S102 - sandboxed on purpose

    try:
        _run_with_timeout(_exec, EXEC_TIMEOUT_SECONDS)
    except _SandboxTimeoutError as exc:
        return {"status": "error", "result_summary": None, "error": str(exc)}
    except Exception as exc:  # generated code can raise anything
        return {"status": "error", "result_summary": None, "error": f"{type(exc).__name__}: {exc}"}

    if "result" not in local_vars:
        return {
            "status": "error",
            "result_summary": None,
            "error": "Generated code did not assign a 'result' variable.",
        }

    try:
        summary = _summarize_result(local_vars["result"])
    except Exception as exc:
        return {"status": "error", "result_summary": None, "error": f"Failed to summarize result: {exc}"}

    return {"status": "success", "result_summary": summary, "error": None}
