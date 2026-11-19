# Worker entry: runs the Python analyzer off the main thread.
# worker.js (Pyodide in a Web Worker) loads this and calls run() for each message,
# JSON in and JSON out, with no DOM access.
import json
from showcase import analyze


def run(expression: str) -> str:
  try:
    return json.dumps(analyze(str(expression)))
  except Exception as e:  # unexpected library failure: surface it instead of hanging the UI
    return json.dumps(dict(input=str(expression), ok=False, stage='crash', errors=[dict(message=f'{type(e).__name__}: {e}')]))
