# Corrosion Segmentation - deployment bundle

The app an intern ships at the end of Topic 6. Three files do the work:

| File | What |
|---|---|
| `app.py` | Streamlit UI: single image, bulk upload, documentation |
| `corrosion_kit.py` | model + inference, copied from the notebooks so nothing drifts |
| `best.pt` | the trained checkpoint, written by the training notebook |

Optional, and worth including - the documentation tab reads them:

| File | What |
|---|---|
| `report.json` | per-class test IoU from the evaluation notebook |
| `history.csv` | per-epoch training curve |
| `examples/*.jpg` | a few photographs so a reviewer can click something immediately |

## Run it locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Ship it from ATLAS

The deployment notebook (`corrosion-5-deployment`) assembles exactly this
folder, zips it, self-checks it against the five rubric rules and can upload it
straight to the platform. Otherwise: **Deployment -> New app -> upload the zip
-> Deploy**, then paste the resulting URL into your Whimsical board.

## Rubric

| Rule | Where it is satisfied |
|---|---|
| R1 Streamlit or Gradio | `import streamlit as st` |
| R2 single + bulk input | Single image tab, Bulk upload tab (multi-file and .zip) |
| R3 documentation | Documentation tab: dataset, architecture, evaluation, limitations |
| R4 confidence + chart | Confidence metrics, per-class area chart, confidence map |
| R5 Whimsical URL | Sidebar link, set `WHIMSICAL_URL` to your board |
