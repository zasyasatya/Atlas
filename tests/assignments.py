"""Does the assignment gate actually hold?

The interesting failure mode is not "the list is filtered" - it is a filtered
list next to an unfiltered detail endpoint, so an intern who guesses a slug
still reads the material. These checks walk every route that can leak topic
content and assert it 404s in production for an unassigned topic, while staying
open in development.

Run against a live pair of servers:
    dev  on :8000  (ATLAS_ENVIRONMENT=development)
    prod on :8100  (ATLAS_ENVIRONMENT=production)
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

DEV = "http://127.0.0.1:8000"
PROD = "http://127.0.0.1:8100"

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    mark = "ok  " if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  -- {detail}" if detail and not cond else ""))


def call(base: str, path: str, token: str | None = None, method: str = "GET",
         body: dict | None = None) -> tuple[int, object]:
    req = urllib.request.Request(base + path, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data, timeout=30) as r:
            raw = r.read()
            try:
                return r.status, json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                return r.status, raw   # binary body, e.g. a zip
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, None
    except urllib.error.URLError as e:
        print(f"\n!! cannot reach {base}: {e}\n")
        sys.exit(2)


def login(base: str, email: str, password: str) -> str:
    status, body = call(base, "/api/auth/login", method="POST",
                        body={"email": email, "password": password})
    if status != 200 or not isinstance(body, dict):
        print(f"!! login failed for {email} on {base}: {status}")
        sys.exit(2)
    return body["access_token"]


def main() -> int:
    print("\n== assignment gating ==\n")

    dev_intern = login(DEV, "intern@atlas.id", "intern123")
    prod_intern = login(PROD, "intern@atlas.id", "intern123")
    prod_sup = login(PROD, "supervisor@atlas.id", "supervisor123")

    # ---------------------------------------------------------- development
    print("development - nothing is hidden")
    status, dev_topics = call(DEV, "/api/topics", dev_intern)
    check("dev: intern sees all 6 topics", status == 200 and len(dev_topics) == 6,
          f"{status} {len(dev_topics) if isinstance(dev_topics, list) else dev_topics}")

    status, acc = call(DEV, "/api/my-access", dev_intern)
    check("dev: my-access reports not enforced",
          status == 200 and acc.get("enforced") is False and acc.get("restricted") is False,
          str(acc))

    status, _ = call(DEV, "/api/topics/report-nlp", dev_intern)
    check("dev: unassigned topic still readable", status == 200, str(status))

    # ---------------------------------------------------------- production
    print("\nproduction - only assigned topics")
    status, prod_topics = call(PROD, "/api/topics", prod_intern)
    slugs = {t["slug"] for t in prod_topics} if isinstance(prod_topics, list) else set()
    check("prod: intern sees exactly the 3 seeded assignments",
          status == 200 and len(prod_topics) == 3, f"{status} {sorted(slugs)}")
    check("prod: assigned corrosion topic present", "corrosion-segmentation" in slugs)
    check("prod: unassigned report-nlp absent", "report-nlp" not in slugs)

    status, acc = call(PROD, "/api/my-access", prod_intern)
    check("prod: my-access reports restricted",
          status == 200 and acc.get("enforced") is True and acc.get("restricted") is True
          and acc.get("assigned_count") == 3, str(acc))

    # the whole point: a guessed URL must not work
    status, _ = call(PROD, "/api/topics/report-nlp", prod_intern)
    check("prod: guessed topic slug 404s", status == 404, str(status))

    status, _ = call(PROD, "/api/topics/corrosion-segmentation", prod_intern)
    check("prod: assigned topic still opens", status == 200, str(status))

    # notebooks follow their topic
    status, nbs = call(PROD, "/api/notebooks", prod_intern)
    nb_topics = {n["topic_id"] for n in nbs} if isinstance(nbs, list) else set()
    # Three assigned topics, but corrosion alone carries five notebooks.
    check("prod: notebook list filtered", status == 200 and len(nbs) == 7,
          f"{status} {len(nbs) if isinstance(nbs, list) else nbs}")

    # find a notebook the intern must not have
    status, all_nbs = call(PROD, "/api/notebooks", prod_sup)
    forbidden = [n for n in all_nbs if n["topic_id"] not in nb_topics]
    check("prod: supervisor sees every notebook", len(all_nbs) == 10, str(len(all_nbs)))

    if forbidden:
        nb_id = forbidden[0]["id"]
        status, _ = call(PROD, f"/api/notebooks/{nb_id}", prod_intern)
        check("prod: unassigned notebook 404s", status == 404, str(status))
        status, _ = call(PROD, f"/api/notebooks/{nb_id}/export.ipynb", prod_intern)
        check("prod: unassigned notebook export 404s", status == 404, str(status))

    # the assigned ones still work, cells and all
    allowed = [n for n in all_nbs if n["topic_id"] in nb_topics]
    opened = 0
    for notebook in allowed:
        status, nb = call(PROD, f"/api/notebooks/{notebook['id']}", prod_intern)
        cells = nb.get("content", {}).get("cells", []) if isinstance(nb, dict) else []
        if status == 200 and len(cells) >= 6:
            opened += 1
    check("prod: every assigned notebook opens with cells",
          opened == len(allowed), f"{opened}/{len(allowed)}")

    # supervisors are never restricted
    status, sup_topics = call(PROD, "/api/topics", prod_sup)
    check("prod: supervisor sees all 6", status == 200 and len(sup_topics) == 6, str(status))

    # ---------------------------------------------------------- management
    print("\nsupervisor manages assignments")
    status, users = call(PROD, "/api/assignable-users", prod_sup)
    check("assignable-users lists interns", status == 200 and len(users) >= 1, str(status))

    status, _ = call(PROD, "/api/assignable-users", prod_intern)
    check("intern cannot list assignable users", status == 403, str(status))

    intern_id = next(u["id"] for u in users if u["email"] == "intern@atlas.id")
    target = next(t for t in sup_topics if t["slug"] == "report-nlp")

    # grant, verify, revoke, verify - the full round trip
    status, rows = call(PROD, "/api/assignments/bulk", prod_sup, method="PUT",
                        body={"user_id": intern_id,
                              "topic_ids": [t["id"] for t in sup_topics]})
    check("bulk assign all 6 succeeds", status == 200 and len(rows) == 6, str(status))

    status, after = call(PROD, "/api/topics", prod_intern)
    check("intern now sees all 6", status == 200 and len(after) == 6, str(len(after)))

    status, _ = call(PROD, f"/api/topics/{target['slug']}", prod_intern)
    check("newly assigned topic opens", status == 200, str(status))

    # back to the seeded three
    seeded = [t["id"] for t in sup_topics
              if t["slug"] in {"predictive-maintenance", "pid-extractor", "corrosion-segmentation"}]
    status, rows = call(PROD, "/api/assignments/bulk", prod_sup, method="PUT",
                        body={"user_id": intern_id, "topic_ids": seeded})
    check("bulk revoke back to 3", status == 200 and len(rows) == 3, str(status))

    status, _ = call(PROD, f"/api/topics/{target['slug']}", prod_intern)
    check("revoked topic 404s again", status == 404, str(status))

    status, _ = call(PROD, "/api/assignments/bulk", prod_intern, method="PUT",
                     body={"user_id": intern_id, "topic_ids": []})
    check("intern cannot assign to themselves", status == 403, str(status))

    status, _ = call(PROD, "/api/assignments/bulk", prod_sup, method="PUT",
                     body={"user_id": intern_id, "topic_ids": [9999]})
    check("unknown topic id rejected", status == 400, str(status))

    # ---------------------------------------------------------- pipelines
    print("\npipeline library")
    status, pipes = call(PROD, "/api/pipelines", prod_intern)
    slugs = {p["slug"] for p in pipes} if isinstance(pipes, list) else set()
    check("intern sees corrosion pipeline (topic assigned)",
          status == 200 and "corrosion-unet" in slugs, f"{status} {sorted(slugs)}")

    status, pipe = call(PROD, "/api/pipelines/corrosion-unet", prod_intern)
    files = {f["path"] for f in pipe.get("files", [])} if isinstance(pipe, dict) else set()
    check("pipeline exposes app.py - the file the lesson names",
          status == 200 and "app.py" in files, str(status))
    check("pipeline ships the corrosion package",
          "corrosion/model.py" in files and "corrosion/train.py" in files)
    check("training bulk is excluded",
          not any(f.startswith(("runs/", "data/", ".venv-app/")) for f in files),
          str(sorted(f for f in files if "/" in f))[:120])

    status, body = call(PROD, "/api/pipelines/corrosion-unet/file?path=app.py", prod_intern)
    content = body.get("content", "") if isinstance(body, dict) else ""
    check("app.py reads back with real content",
          status == 200 and "streamlit" in content.lower() and len(content) > 5000,
          f"{status} {len(content)} chars")

    for bad in ["../../.env", "/etc/passwd", "runs/smoke/best.pt", "../../../etc/hosts"]:
        status, _ = call(PROD, f"/api/pipelines/corrosion-unet/file?path={bad}", prod_intern)
        check(f"path traversal blocked: {bad}", status == 404, str(status))

    status, zbody = call(PROD, "/api/pipelines/corrosion-unet/download", prod_intern)
    check("zip download works",
          status == 200 and isinstance(zbody, bytes) and zbody[:2] == b"PK",
          f"{status} {len(zbody) if isinstance(zbody, bytes) else 0} bytes")

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("\nfailures:")
        for f in FAIL:
            print("  -", f)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
