# Open Signal worker

Python ingestion, analysis, agents and composer (spec §117.2).

The `open_signal` package lives at the repo root under `/python` and is
installed through this project's `pyproject.toml` (hatch path `../python`).

```powershell
pip install -e ./apps/worker[dev]
python -c "import open_signal; print(open_signal.__version__)"
```
