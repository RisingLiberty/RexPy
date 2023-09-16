import time
from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler, FileSystemEvent, FileSystemMovedEvent

class DirWatcher():
    def __init__(self, dir : str, bRecursive : bool):
        patterns = ["*"]
        ignore_patterns = None
        ignore_directories = False
        case_sensitive = True
        self.event_handler = PatternMatchingEventHandler(patterns, ignore_patterns, ignore_directories, case_sensitive)

        self.event_handler.on_created = self._on_created
        self.event_handler.on_deleted = self._on_deleted
        self.event_handler.on_modified = self._on_modified
        self.event_handler.on_moved = self._on_moved
    
        path = "."
        go_recursively = True
        self.observer = Observer()
        self.observer.schedule(self.event_handler, path, recursive=go_recursively)

        self.created_or_modified_files : list[str] = []
        self.deleted_files : list[str] = []

    def __enter__(self):
        self.observer.start()       
        return self

    def __exit__(self, exception_type, exception_value, traceback):
        # Wait 1.5 seconds, making sure all event are processed
        time.sleep(1.5)

        self.observer.stop()
        self.observer.join()

    def _on_created(self, event : FileSystemEvent):
        if event.src_path not in self.created_or_modified_files:
            self.created_or_modified_files.append(event.src_path)
    
    def _on_deleted(self, event : FileSystemEvent):
        if event.src_path not in self.deleted_files:
            self.deleted_files.append(event.src_path)
    
    def _on_modified(self, event : FileSystemEvent):
        if event.src_path not in self.created_or_modified_files:
            self.created_or_modified_files.append(event.src_path)
    
    def _on_moved(self, event : FileSystemMovedEvent):
        if event.src_path not in self.created_or_modified_files:
            self.created_or_modified_files.append(event.dest_path)
        
        if event.src_path not in self.deleted_files:
            self.deleted_files.append(event.src_path)

    def filter_created_or_modified_files(self, func):
        return list(filter(func, self.created_or_modified_files))
    
    def filter_deleted_files(self, func):
        return list(filter(func, self.created_or_modified_files))

