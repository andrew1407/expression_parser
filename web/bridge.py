# PyScript entry: exposes the Python analyzer to the page's JavaScript.
import json
from pyscript import window
from pyodide.ffi import create_proxy
from showcase import analyze


def run(expression: str) -> str:
  try:
    return json.dumps(analyze(str(expression)))
  except Exception as e:  # unexpected library failure: surface it instead of hanging the UI
    return json.dumps(dict(input=str(expression), ok=False, stage='crash', errors=[dict(message=f'{type(e).__name__}: {e}')]))


window.pyAnalyze = create_proxy(run)
window.dispatchEvent(window.CustomEvent.new('py-ready'))
