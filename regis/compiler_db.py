import os
import json

class CompileDBEntry:
  def __init__(self, jsonEntry):
    self.directory = jsonEntry['directory']
    self.command = jsonEntry['command']
    self.file = jsonEntry['file']
    self.output = jsonEntry['output']

class CompileDB:
  def __init__(self, path):
    database = json.load(open('compile_commands.json'))
    self.entries = list([CompileDBEntry(entry)
           for entry in database])

db = CompileDB('compile_commands.json')
for entry in db.entries:
  print(entry.file)