# Signal Sudoku

Streamlit app for industrial I/O signal allocation (hackathon MVP).

**App code lives in [`Signal_Sudoku/`](Signal_Sudoku/).** Full run, host, and deploy steps are in [`Signal_Sudoku/README.md`](Signal_Sudoku/README.md).

## Quick start (Windows)

```powershell
cd Signal_Sudoku
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
streamlit run app.py
```

Open **http://localhost:8501** in your browser.

## Host on LAN

```powershell
streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

## Deploy publicly

Push `Signal_Sudoku/` to GitHub, then create an app at [share.streamlit.io](https://share.streamlit.io/) with main file `app.py` (or `Signal_Sudoku/app.py` if the repo root is this parent folder).
