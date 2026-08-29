"""Code injected into every notebook so remote runtimes report back to ATLAS.

The bridge cell is prepended at dispatch time. It gives the notebook:
  * ATLAS_RUN_ID / ATLAS_TOKEN / ATLAS_API  -> identity + callback endpoint
  * atlas.log(...)      stream logs into the run timeline
  * atlas.metric(...)   push metrics (accuracy, MAE, MAPE, IoU...)
  * atlas.dataset()     download the dataset attached to this run
  * atlas.artifact(...) upload trained weights back to the platform
  * atlas.finish(...)   mark the run succeeded/failed
"""
from __future__ import annotations

BRIDGE_SOURCE = '''# --- ATLAS bridge (auto-injected, do not edit) -------------------------------
import json, os, time, urllib.request, urllib.error

ATLAS_API = os.environ.get("ATLAS_API", "{api_base}")
ATLAS_RUN_ID = os.environ.get("ATLAS_RUN_ID", "{run_id}")
ATLAS_TOKEN = os.environ.get("ATLAS_TOKEN", "{token}")


class _Atlas:
    """Tiny stdlib-only client so it works on a bare Colab/Kaggle runtime."""

    def __init__(self):
        self._buffer = []
        self._metrics = {{}}

    def _post(self, payload, path=""):
        url = f"{{ATLAS_API}}/api/runs/{{ATLAS_RUN_ID}}/callback{{path}}"
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={{"Content-Type": "application/json", "X-Atlas-Token": ATLAS_TOKEN}},
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode() or "{{}}")
        except Exception as exc:  # offline runs must never crash the notebook
            print(f"[atlas] callback skipped: {{exc}}")
            return {{}}

    def log(self, *parts):
        line = " ".join(str(p) for p in parts)
        print(line)
        self._buffer.append(line)
        if len(self._buffer) >= 5:
            self.flush()

    def flush(self):
        if self._buffer:
            self._post({{"status": "running", "logs": "\\n".join(self._buffer)}})
            self._buffer = []

    def metric(self, **kwargs):
        self._metrics.update(kwargs)
        self._post({{"status": "running", "metrics": self._metrics}})
        for k, v in kwargs.items():
            print(f"[atlas] metric {{k}} = {{v}}")

    def dataset(self, dest="dataset"):
        """Download the dataset attached to this run (returns local path)."""
        url = f"{{ATLAS_API}}/api/runs/{{ATLAS_RUN_ID}}/dataset?token={{ATLAS_TOKEN}}"
        os.makedirs(dest, exist_ok=True)
        target = os.path.join(dest, "data.bin")
        try:
            urllib.request.urlretrieve(url, target)
            self.log(f"dataset downloaded -> {{target}}")
            return target
        except Exception as exc:
            self.log(f"no dataset attached ({{exc}})")
            return None

    def artifact(self, path):
        """Upload a trained model / figure back to ATLAS."""
        try:
            with open(path, "rb") as fh:
                body = fh.read()
        except OSError as exc:
            self.log(f"artifact missing: {{exc}}")
            return
        name = os.path.basename(path)
        boundary = "----atlas" + str(int(time.time()))
        pre = (f"--{{boundary}}\\r\\nContent-Disposition: form-data; name=\\"file\\"; "
               f"filename=\\"{{name}}\\"\\r\\nContent-Type: application/octet-stream\\r\\n\\r\\n").encode()
        post = f"\\r\\n--{{boundary}}--\\r\\n".encode()
        req = urllib.request.Request(
            f"{{ATLAS_API}}/api/runs/{{ATLAS_RUN_ID}}/artifact?token={{ATLAS_TOKEN}}",
            data=pre + body + post, method="POST",
            headers={{"Content-Type": f"multipart/form-data; boundary={{boundary}}"}},
        )
        try:
            urllib.request.urlopen(req, timeout=120)
            self.log(f"artifact uploaded: {{name}}")
        except Exception as exc:
            self.log(f"artifact upload failed: {{exc}}")

    def finish(self, status="succeeded", error=""):
        self.flush()
        self._post({{"status": status, "metrics": self._metrics, "error": error}})
        print(f"[atlas] run {{status}}")


atlas = _Atlas()
try:
    import torch
    _dev = "GPU: " + torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU only"
except Exception:
    _dev = "torch not installed"
atlas.log(f"ATLAS bridge ready | run={{ATLAS_RUN_ID}} | {{_dev}}")
# -----------------------------------------------------------------------------
'''


def build_bridge_cell(api_base: str, run_id: int, token: str) -> str:
    return BRIDGE_SOURCE.format(api_base=api_base.rstrip("/"), run_id=run_id, token=token)
