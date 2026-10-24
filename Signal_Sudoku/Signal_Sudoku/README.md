# Signal Sudoku

Industrial I/O signal allocation prototype (hackathon MVP). Assigns signals to cabinets, CIOCs, baseplates, and CHARM slots. **Not certified for real plant engineering use** — review all outputs with a qualified engineer.

## Prerequisites

- **Python 3.10–3.13** (recommended). Python 3.14 may not have compatible wheels for Streamlit/pandas yet.
- Windows, macOS, or Linux
- A terminal (PowerShell, Command Prompt, or bash)

## Run locally (Windows)

From the folder that contains `app.py` (this directory: `Signal_Sudoku/`):

```powershell
# 1. Create a virtual environment (once)
py -3.13 -m venv .venv

# 2. Activate it
.\.venv\Scripts\Activate.ps1

# 3. Install dependencies
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# 4. (Optional) Regenerate synthetic sample Excel workbooks
python sample_data/create_sample_data.py

# 5. Start the app
streamlit run app.py
```

The app opens in your browser at **http://localhost:8501**.

If activation fails in PowerShell (`execution of scripts is disabled`), run once:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### Alternative: run from the parent folder

If your shell is in the repo root (`Project/Signal_Sudoku/`):

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r Signal_Sudoku\requirements.txt
streamlit run Signal_Sudoku\app.py
```

## Run locally (macOS / Linux)

```bash
cd Signal_Sudoku   # folder with app.py
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Host on your local network

To let others on the same Wi‑Fi/LAN open the app:

```powershell
streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

Share `http://<your-pc-ip>:8501` (find your IP with `ipconfig` on Windows). Allow the port in Windows Firewall if prompted.

## Deploy to Streamlit Community Cloud (public URL)

1. Push this project to a **GitHub** repository. Keep together:
   - `app.py`
   - `requirements.txt`
   - `core/`, `services/`, `config/`, `sample_data/`, `.streamlit/`
2. Go to [share.streamlit.io](https://share.streamlit.io/) and sign in with GitHub.
3. **Create app** → select the repo and branch.
4. Set **Main file path** to `app.py` (or `Signal_Sudoku/app.py` if this folder sits inside a larger repo).
5. Deploy. Streamlit installs packages from `requirements.txt` and gives you a public URL.

**Notes**

- The app loads the included synthetic sample workbook, so it works without uploading files first.
- **Save rules** writes `config/user_rules.json` on the server. Cloud restarts can wipe that file — keep a local copy of any rules you care about.
- Uploaded workbooks are processed in memory and are not stored in the repository.

## Tests

```powershell
python -m pytest -q
```

## Project layout

| Path | Role |
|------|------|
| `app.py` | Streamlit UI entry point |
| `core/` | Allocation, validation, reports, revision workflow |
| `services/` | Excel I/O and configuration |
| `config/` | Default (and optional user) rules |
| `sample_data/` | Synthetic Excel generators and samples |
| `tests/` | pytest suite |
| `requirements.txt` | Python dependencies |

## Sample data

`sample_data/create_sample_data.py` builds clean input, intentionally flawed input, a later revision, and an overflow dataset for development. These are **not** official hackathon-provided test files.

## Scope and limitations

- Configurable capacity, segregation, grouping, pair ordering, and spare capacity
- Unknown I/O types are left unallocated and receive a TQ
- Deterministic first-fit allocation with post-allocation checks
- Excel export: allocation, validation, TQ, hardware summary, configuration
- Revision comparison by signal tag and source fields
- Cable grouping is best-effort; oversized cables may span baseplates
- Exports use generated sheets (no vendor template fill-in)
- Always validate outputs before any real-world use
