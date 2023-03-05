import json
import os
import regis.diagnostics

def load_file(path):
  if not os.path.exists(path):
    regis.diagnostics.log_err(f"Failed to load json, file does not exist '{path}'")
    return None

  f = open(path)
  data = json.load(f)
  return data

def save_file(path : str, data):
  f = open(path, "w")
  json.dump(data, f, indent=2)