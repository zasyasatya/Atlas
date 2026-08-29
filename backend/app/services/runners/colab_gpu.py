"""Colab GPU bridge.

Strategy (no GPU needed on the platform host):
  1. Materialise the notebook + injected ATLAS bridge cell.
  2. Publish it somewhere Colab can fetch:
       - GitHub repo (if a token is configured)  -> colab.research.google.com/github/...
       - otherwise a signed platform URL         -> colab.research.google.com/#fileId=<url>
  3. The learner clicks "Open in Colab", picks Runtime > GPU, Run all.
  4. The injected bridge streams logs/metrics/artifacts back to ATLAS,
     so the run timeline fills in live even though compute is remote.
"""
from __future__ import annotations

import base64
import json

import httpx

from app.core.config import settings
from app.domain.enums import RunStatus
from app.domain.models import Notebook, Run
from app.services.runners.base import LaunchResult
from app.services.runners.bridge import build_bridge_cell


class ColabRunner:
    name = "colab_gpu"

    def launch(self, run: Run, notebook: Notebook) -> LaunchResult:
        api_base = settings.public_base_url or "http://127.0.0.1:8000"
        doc = json.loads(notebook.content_json or "{}")
        bridge = {
            "cell_type": "code",
            "metadata": {"atlas": "bridge"},
            "source": build_bridge_cell(api_base, run.id or 0, run.callback_token).splitlines(keepends=True),
            "outputs": [],
            "execution_count": None,
        }
        doc.setdefault("cells", [])
        doc["cells"] = [bridge] + doc["cells"]
        doc.setdefault("metadata", {})["accelerator"] = "GPU"
        doc["metadata"]["colab"] = {"provenance": [], "gpuType": "T4"}
        payload = json.dumps(doc, ensure_ascii=False, indent=1)

        path = f"runs/atlas_run_{run.id}.ipynb"
        if settings.github_token and settings.colab_github_repo:
            url, log = self._push_to_github(path, payload)
            if url:
                return LaunchResult(
                    status=RunStatus.QUEUED,
                    external_url=url,
                    logs=log,
                    instructions=[
                        "Open the Colab link below.",
                        "Runtime -> Change runtime type -> T4 GPU -> Save.",
                        "Runtime -> Run all. Metrics stream back here automatically.",
                    ],
                )

        # Fallback: serve the notebook from ATLAS and let Colab import it by URL.
        raw = f"{api_base}/api/runs/{run.id}/notebook.ipynb?token={run.callback_token}"
        colab = f"https://colab.research.google.com/#create=true&url={raw}"
        return LaunchResult(
            status=RunStatus.QUEUED,
            external_url=colab,
            logs=("GitHub bridge not configured - using direct URL import.\n"
                  "Set ATLAS_GITHUB_TOKEN + ATLAS_COLAB_GITHUB_REPO for one-click repo sync."),
            instructions=[
                "Open in Colab, then Runtime -> Change runtime type -> T4 GPU.",
                "Run all cells. The ATLAS bridge reports progress back to this run.",
                f"If Colab asks for a source, use: {raw}",
            ],
        )

    def _push_to_github(self, path: str, content: str) -> tuple[str, str]:
        repo, branch = settings.colab_github_repo, settings.colab_github_branch
        api = f"https://api.github.com/repos/{repo}/contents/{path}"
        headers = {
            "Authorization": f"Bearer {settings.github_token}",
            "Accept": "application/vnd.github+json",
        }
        try:
            with httpx.Client(timeout=30) as client:
                sha = None
                probe = client.get(api, headers=headers, params={"ref": branch})
                if probe.status_code == 200:
                    sha = probe.json().get("sha")
                body = {
                    "message": f"atlas: dispatch {path}",
                    "content": base64.b64encode(content.encode()).decode(),
                    "branch": branch,
                }
                if sha:
                    body["sha"] = sha
                resp = client.put(api, headers=headers, json=body)
                if resp.status_code in (200, 201):
                    return (f"https://colab.research.google.com/github/{repo}/blob/{branch}/{path}",
                            f"Notebook pushed to {repo}@{branch}:{path}")
                return "", f"GitHub push failed ({resp.status_code}): {resp.text[:300]}"
        except Exception as exc:
            return "", f"GitHub push error: {exc}"
