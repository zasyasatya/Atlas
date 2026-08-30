"""Execute a notebook on the platform CPU, isolated in a subprocess."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.core.db import session_scope
from app.domain.enums import RunStatus
from app.domain.models import Notebook, Run
from app.services.runners.base import LaunchResult
from app.services.runners.bridge import build_bridge_cell

BACKEND_ROOT = Path(__file__).resolve().parents[3]
TIMEOUT_SECONDS = 1200


class LocalCpuRunner:
    name = "local_cpu"

    def launch(self, run: Run, notebook: Notebook) -> LaunchResult:
        threading.Thread(target=self._execute, args=(run.id, notebook.id), daemon=True).start()
        return LaunchResult(
            status=RunStatus.RUNNING,
            logs="Dispatched to the platform CPU worker.",
            instructions=["Executing on the built-in CPU kernel.",
                          "Heavy vision training should target Colab GPU or Kaggle GPU."],
        )

    def _execute(self, run_id: int, notebook_id: int) -> None:
        started = time.time()
        workdir = settings.storage_dir / "runs" / f"run_{run_id}"
        workdir.mkdir(parents=True, exist_ok=True)

        with session_scope() as session:
            run, notebook = session.get(Run, run_id), session.get(Notebook, notebook_id)
            if not run or not notebook:
                return
            # A topic can be a pipeline: stage 1 writes a manifest, stage 2 a
            # checkpoint, stage 3 a report. Each run gets its own directory, so
            # without a shared workspace stage 3 would open on an empty folder
            # and tell the intern to go and train a model they already trained.
            workspace = (settings.storage_dir / "runs" / "workspaces"
                         / f"topic{run.topic_id}_user{run.user_id}")
            workspace.mkdir(parents=True, exist_ok=True)
            run.status = RunStatus.RUNNING
            run.started_at = datetime.now(timezone.utc)
            session.add(run)
            session.commit()
            doc = json.loads(notebook.content_json or "{}")
            token = run.callback_token

        api_base = settings.public_base_url or "http://127.0.0.1:8000"
        bridge = {"id": "atlasbridge", "cell_type": "code", "metadata": {}, "execution_count": None,
                  "outputs": [],
                  "source": build_bridge_cell(api_base, run_id, token).splitlines(keepends=True)}
        doc.setdefault("cells", [])
        doc["cells"] = [bridge] + doc["cells"]

        nb_path, out_path = workdir / "notebook.ipynb", workdir / "result.json"
        nb_path.write_text(json.dumps(doc, ensure_ascii=False))

        status, error, logs = RunStatus.FAILED, "", ""
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "app.services.runners._exec_notebook",
                 str(nb_path), str(out_path)],
                cwd=str(BACKEND_ROOT), capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
                env=dict(os.environ, ATLAS_WORK=str(workspace)),
            )
            if out_path.exists():
                payload = json.loads(out_path.read_text())
                status = RunStatus.SUCCEEDED if payload["status"] == "succeeded" else RunStatus.FAILED
                error, logs = payload.get("error", ""), payload.get("logs", "")
            else:
                error = (proc.stderr or proc.stdout or "Executor produced no result.")[-4000:]
        except subprocess.TimeoutExpired:
            error = f"Notebook exceeded the {TIMEOUT_SECONDS // 60} minute CPU limit. Use a GPU target."
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"[:4000]

        with session_scope() as session:
            run = session.get(Run, run_id)
            if not run:
                return
            run.logs = ((run.logs or "") + "\n" + logs)[-20000:]
            run.status = status
            run.error = error
            run.finished_at = datetime.now(timezone.utc)
            run.duration_seconds = round(time.time() - started, 2)
            session.add(run)
            session.commit()
