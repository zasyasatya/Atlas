"""Standalone notebook executor.

Run as a subprocess so nbclient owns a real main thread (it installs signal
handlers, which fails inside a worker thread) and so a runaway notebook can be
killed without touching the API process.

usage: python -m app.services.runners._exec_notebook <in.ipynb> <out.json>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    src, dest = Path(sys.argv[1]), Path(sys.argv[2])
    import nbformat
    from nbclient import NotebookClient
    from nbclient.exceptions import CellExecutionError

    nb = nbformat.read(src, as_version=4)
    result = {"status": "succeeded", "error": "", "logs": ""}
    try:
        NotebookClient(nb, timeout=900, kernel_name="python3", allow_errors=False,
                       resources={"metadata": {"path": str(src.parent)}}).execute()
    except CellExecutionError as exc:
        result.update(status="failed", error=str(exc)[:4000])
    except Exception as exc:  # noqa: BLE001
        result.update(status="failed", error=f"{type(exc).__name__}: {exc}"[:4000])

    logs: list[str] = []
    for cell in nb.cells:
        for out in cell.get("outputs", []) or []:
            kind = out.get("output_type")
            if kind == "stream":
                logs.append(out.get("text", ""))
            elif kind == "execute_result":
                logs.append(str(out.get("data", {}).get("text/plain", "")))
            elif kind == "error":
                logs.append("\n".join(out.get("traceback", []))[:2000])
    result["logs"] = "".join(logs)[-20000:]
    dest.write_text(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
