# v0.8.50: Excel works on the live site (missing package on Vercel)

Found with the v0.8.49 error reference: `ModuleNotFoundError: No module named 'openpyxl'` on Finance → Import expenses → Download template.

**Cause:** Vercel installs the packages listed in `pyproject.toml`, not `requirements.txt`. The Excel library (openpyxl, added in v0.8.38) was only ever added to `requirements.txt`. So on the live site every Excel feature failed: the import templates, Check file / Import, and every "Download Excel". Tests and local runs use requirements.txt, so they never saw it.

**Fix:** `pyproject.toml` now lists the same packages as `requirements.txt`: openpyxl added; Flask held below 3.2, as in requirements.txt; gunicorn added.

**Guard:** new `tests/test_session50.py` fails if the two lists ever differ again, or if the code imports a package pyproject.toml does not list. It fails on the old file and passes on the new one.

No database change.
