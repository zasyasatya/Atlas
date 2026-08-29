"""Kaggle Kernels GPU bridge - fully headless (30 GPU hours/week, free)."""
from __future__ import annotations

import base64
import json
from datetime import datetime, timezone

import httpx

from app.core.config import settings
from app.domain.enums import RunStatus
from app.domain.models import Notebook, Run
from app.services.runners.base import LaunchResult
from app.services.runners.bridge import build_bridge_cell

KAGGLE_API = "https://www.kaggle.com/api/v1"


class KaggleRunner:
    name = "kaggle_gpu"

    def launch(self, run: Run, notebook: Notebook) -> LaunchResult:
        if not (settings.kaggle_username and settings.kaggle_key):
            return LaunchResult(
                status=RunStatus.PENDING,
                logs="Kaggle credentials missing.",
                error="Set ATLAS_KAGGLE_USERNAME and ATLAS_KAGGLE_KEY to enable headless GPU runs.",
                instructions=[
                    "Kaggle -> Account -> Create New API Token downloads kaggle.json.",
                    "Add the username/key to the platform environment, then re-run.",
                ],
            )

        api_base = settings.public_base_url or "http://127.0.0.1:8000"
        doc = json.loads(notebook.content_json or "{}")
        bridge = {
            "cell_type": "code",
            "metadata": {},
            "source": build_bridge_cell(api_base, run.id or 0, run.callback_token).splitlines(keepends=True),
            "outputs": [],
            "execution_count": None,
        }
        doc.setdefault("cells", [])
        doc["cells"] = [bridge] + doc["cells"]

        slug = f"atlas-run-{run.id}-{datetime.now(timezone.utc).strftime('%H%M%S')}"
        meta = {
            "id": f"{settings.kaggle_username}/{slug}",
            "title": f"ATLAS run {run.id} - {notebook.title}"[:50],
            "code_file": "notebook.ipynb",
            "language": "python",
            "kernel_type": "notebook",
            "is_private": True,
            "enable_gpu": True,
            "enable_internet": True,
            "dataset_sources": [],
            "competition_sources": [],
            "kernel_sources": [],
        }
        blob = json.dumps(doc, ensure_ascii=False)
        payload = {
            "id": meta["id"],
            "slug": slug,
            "newTitle": meta["title"],
            "text": blob,
            "language": "python",
            "kernelType": "notebook",
            "isPrivate": True,
            "enableGpu": True,
            "enableInternet": True,
            "datasetDataSources": [],
            "competitionDataSources": [],
            "kernelDataSources": [],
            "categoryIds": [],
        }
        auth = base64.b64encode(f"{settings.kaggle_username}:{settings.kaggle_key}".encode()).decode()
        try:
            with httpx.Client(timeout=60) as client:
                resp = client.post(
                    f"{KAGGLE_API}/kernels/push",
                    headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
                    json=payload,
                )
            if resp.status_code >= 400:
                return LaunchResult(status=RunStatus.FAILED, error=f"Kaggle push failed: {resp.text[:400]}")
            data = resp.json()
            url = data.get("url") or f"https://www.kaggle.com/code/{settings.kaggle_username}/{slug}"
            return LaunchResult(
                status=RunStatus.QUEUED,
                external_url=url,
                logs=f"Kernel queued on Kaggle GPU: {url}",
                instructions=["Kaggle is executing the notebook on a free T4/P100.",
                              "Logs and metrics stream back here through the ATLAS bridge."],
            )
        except Exception as exc:
            return LaunchResult(status=RunStatus.FAILED, error=f"Kaggle dispatch error: {exc}")
