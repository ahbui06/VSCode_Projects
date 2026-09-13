"""Execute the notebook's default offline demo in a real Jupyter kernel."""
import os
from pathlib import Path

import nbformat
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
output = ROOT / "outputs"
output.mkdir(exist_ok=True)
for variable, name in (("JUPYTER_RUNTIME_DIR", "jupyter_runtime"),
                       ("IPYTHONDIR", "ipython"), ("MPLCONFIGDIR", "matplotlib")):
    directory = output / name
    directory.mkdir(exist_ok=True)
    os.environ[variable] = str(directory)
notebook = nbformat.read(ROOT / "Electricity_Agreement_Optimizer.ipynb", as_version=4)
nbformat.validate(notebook)
NotebookClient(notebook, timeout=120, kernel_name="python3", resources={"metadata": {"path": str(ROOT)}}).execute()
nbformat.write(notebook, output / "demo_executed.ipynb")
print("Notebook executed successfully; saved outputs/demo_executed.ipynb")
