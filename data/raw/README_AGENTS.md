DATA RULES FOR THIS PROJECT (Texas Legislature 2026 Forecast)
- Public sources only. Never fabricate or guess a number. If a value is unknown, leave it blank and say so in NOTES.md.
- For EVERY file you save, add an entry to manifest.json in your directory:
  [{"file": "...", "url": "...", "retrieved_at": "YYYY-MM-DDTHH:MM", "description": "..."}]
- Save the raw page/CSV you parsed (HTML or CSV) next to your parsed output, so parsing can be re-run.
- Write NOTES.md: what you found, what was missing/paywalled/bot-blocked, and alternatives you used.
- Use curl with a desktop User-Agent, or the venv python: <project>/.venv/bin/python (pandas, requests, bs4, lxml, pdfplumber installed). Install extra packages into that venv only.
- Keep scripts you write in <project>/pipeline/fetch/ (create it), named fetch_<topic>.py, runnable with no arguments, writing into your data directory. The pipeline will re-run them later, so they must be deterministic and must not depend on files you edited by hand.
