"""Graduation rubric: the 5 web-app requirements, auto-checked against a bundle.

Rules mirror the supervisor's checklist:
  R1 framework is Streamlit or Gradio
  R2 input form supports single entry AND bulk spreadsheet upload
  R3 documentation page covers limitations / dataset / architecture / evaluation
  R4 output shows confidence (classification) or MAPE (forecasting) + a chart
  R5 deployed URL attached in Whimsical
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from sqlmodel import Session, delete, select

from app.domain.enums import AppFramework, CheckStatus
from app.domain.models import ComplianceCheck, Deployment

TEXT_EXT = {".py", ".md", ".txt", ".toml", ".cfg", ".json", ".yaml", ".yml"}


@dataclass
class Rule:
    id: str
    label: str
    hint: str


RULES: list[Rule] = [
    Rule("R1", "Framework is Streamlit or Gradio",
         "Import streamlit as st, or build a gr.Blocks/gr.Interface app."),
    Rule("R2", "Input form: single entry + bulk spreadsheet upload",
         "Add per-field widgets AND a file uploader accepting .csv/.xlsx."),
    Rule("R3", "Documentation page: limitations, dataset, architecture, evaluation",
         "Add a Documentation tab covering all four sections."),
    Rule("R4", "Output: confidence score / MAPE + visualisation",
         "Show predict_proba confidence for classification or MAPE for forecasting, plus a chart."),
    Rule("R5", "Deployed URL attached in Whimsical",
         "Paste the Whimsical board link on the deployment record."),
]

_PATTERNS = {
    "streamlit": re.compile(r"\bimport\s+streamlit\b|\bstreamlit\s+as\s+st\b", re.I),
    "gradio": re.compile(r"\bimport\s+gradio\b|\bgr\.(Blocks|Interface)\b", re.I),
    "single_input": re.compile(
        r"st\.(number_input|text_input|selectbox|slider|form|radio|date_input)|gr\.(Number|Textbox|Slider|Dropdown|Radio)", re.I),
    "bulk_input": re.compile(
        r"st\.file_uploader|gr\.File|read_csv|read_excel|\.xlsx|\.csv", re.I),
    "doc_limit": re.compile(r"limitation|constraint|batasan|not\s+suitable|out\s+of\s+scope", re.I),
    "doc_dataset": re.compile(r"dataset|data\s+source|number\s+of\s+(rows|parameters|records)|sample size", re.I),
    "doc_arch": re.compile(r"architecture|model\s+(type|works|design)|xgboost|svm|random\s*forest|unet|yolo|resnet|transformer|lstm", re.I),
    "doc_eval": re.compile(r"accuracy|f1|precision|recall|\bmae\b|\brmse\b|\bmape\b|iou|dice|evaluation", re.I),
    "confidence": re.compile(r"confidence|predict_proba|probability|softmax|\bproba\b", re.I),
    "mape": re.compile(r"\bmape\b|mean_absolute_percentage_error", re.I),
    "chart": re.compile(
        r"st\.(line_chart|bar_chart|area_chart|pyplot|plotly_chart|altair_chart|map)|plotly|matplotlib|altair|gr\.(Plot|LinePlot|BarPlot)", re.I),
}


def _collect_text(bundle: Path) -> str:
    if not bundle or not bundle.exists():
        return ""
    chunks: list[str] = []
    for path in bundle.rglob("*"):
        if path.is_file() and path.suffix.lower() in TEXT_EXT and path.stat().st_size < 2_000_000:
            try:
                chunks.append(path.read_text(errors="ignore"))
            except OSError:
                continue
    return "\n".join(chunks)


def evaluate(session: Session, deployment: Deployment, *, task_type: str = "classification") -> list[ComplianceCheck]:
    source = _collect_text(Path(deployment.bundle_path)) if deployment.bundle_path else ""
    results: list[tuple[str, CheckStatus, str]] = []

    # R1
    is_st = bool(_PATTERNS["streamlit"].search(source))
    is_gr = bool(_PATTERNS["gradio"].search(source))
    if is_st or is_gr:
        detected = "Streamlit" if is_st else "Gradio"
        declared = deployment.framework.value
        ok = (is_st and declared == AppFramework.STREAMLIT) or (is_gr and declared == AppFramework.GRADIO)
        results.append(("R1", CheckStatus.PASS if ok else CheckStatus.WARN,
                        f"Detected {detected} in source." + ("" if ok else f" Declared framework is '{declared}'.")))
    else:
        results.append(("R1", CheckStatus.FAIL, "No Streamlit or Gradio import found in the bundle."))

    # R2
    single = bool(_PATTERNS["single_input"].search(source))
    bulk = bool(_PATTERNS["bulk_input"].search(source))
    if single and bulk:
        results.append(("R2", CheckStatus.PASS, "Single-entry widgets and bulk file upload both present."))
    elif single or bulk:
        missing = "bulk spreadsheet upload" if single else "single-entry form"
        results.append(("R2", CheckStatus.FAIL, f"Missing {missing}."))
    else:
        results.append(("R2", CheckStatus.FAIL, "No input widgets detected."))

    # R3
    doc_hits = {k: bool(_PATTERNS[k].search(source)) for k in ("doc_limit", "doc_dataset", "doc_arch", "doc_eval")}
    missing_docs = [k.replace("doc_", "") for k, v in doc_hits.items() if not v]
    if not missing_docs:
        results.append(("R3", CheckStatus.PASS, "Limitations, dataset, architecture and evaluation all documented."))
    else:
        results.append(("R3", CheckStatus.FAIL, f"Documentation missing: {', '.join(missing_docs)}."))

    # R4
    chart = bool(_PATTERNS["chart"].search(source))
    if task_type in ("forecasting", "regression"):
        metric_ok = bool(_PATTERNS["mape"].search(source))
        metric_name = "MAPE"
    else:
        metric_ok = bool(_PATTERNS["confidence"].search(source))
        metric_name = "confidence score"
    if metric_ok and chart:
        results.append(("R4", CheckStatus.PASS, f"{metric_name} and visualisation detected."))
    elif metric_ok:
        results.append(("R4", CheckStatus.WARN, f"{metric_name} present, but no chart detected."))
    else:
        results.append(("R4", CheckStatus.FAIL, f"Mandatory {metric_name} not found in the output path."))

    # R5
    if deployment.whimsical_url.strip():
        ok = "whimsical.com" in deployment.whimsical_url.lower()
        results.append(("R5", CheckStatus.PASS if ok else CheckStatus.WARN,
                        deployment.whimsical_url if ok else "URL provided but does not look like a Whimsical link."))
    else:
        results.append(("R5", CheckStatus.FAIL, "No Whimsical board URL attached."))

    session.exec(delete(ComplianceCheck).where(ComplianceCheck.deployment_id == deployment.id))
    rules_by_id = {r.id: r for r in RULES}
    rows: list[ComplianceCheck] = []
    for rule_id, status, detail in results:
        rule = rules_by_id[rule_id]
        row = ComplianceCheck(
            deployment_id=deployment.id or 0,
            rule_id=rule_id,
            label=rule.label,
            status=status,
            detail=detail if status == CheckStatus.PASS else f"{detail} Fix: {rule.hint}",
        )
        session.add(row)
        rows.append(row)

    passed = sum(1 for _, s, _ in results if s == CheckStatus.PASS)
    warned = sum(1 for _, s, _ in results if s == CheckStatus.WARN)
    deployment.readiness_score = int(round((passed + 0.5 * warned) / len(RULES) * 100))
    session.add(deployment)
    session.commit()
    return rows


def checks_for(session: Session, deployment_id: int) -> list[ComplianceCheck]:
    return list(session.exec(select(ComplianceCheck).where(ComplianceCheck.deployment_id == deployment_id)))
