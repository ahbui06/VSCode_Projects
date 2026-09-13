# Invoice Manager Setup

The notebook uses the standard OpenAI API, not Azure OpenAI. Per official OpenAI documentation, the Python SDK can read your key from `OPENAI_API_KEY`.

## Windows PowerShell

```powershell
cd C:\Users\Nyalo\VSCode_Projects\Invoice_Manager
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
.\.venv\Scripts\python -m ipykernel install --user --name invoice-manager --display-name "Invoice Manager (.venv)"
.\.venv\Scripts\jupyter notebook Invoice-Management.ipynb
```

This machine's current `.venv` was created with Python 3.14.2 because the installed Python 3.11 Windows Store launcher returned `Access is denied`. If you install a standard Python 3.11 or 3.12 build later, recreate `.venv` with that version for broader package compatibility.

Put your real OpenAI API key in `.env`:

```text
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-5
```

In VS Code or Jupyter, select the `Invoice Manager (.venv)` kernel before running the notebook.
