import time
import rexpy.diagnostics

class TaskRaiiPrint(object):
  def __init__(self, msg):
    self._msg = msg
    self._finished_msg = "done"
    self.start_time = time.time()

    rexpy.diagnostics.log_info(msg)
  
  def failed(self):
    self._finished_msg = "failed"

  def __del__(self):
    end_time = time.time()
    rexpy.diagnostics.log_info(f"{self._msg} - {self._finished_msg}")
    rexpy.diagnostics.log_info(f"\ttook {end_time - self.start_time:0.2f} seconds")