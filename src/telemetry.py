"""Append-only task-scoped events; never log model prompts or credentials."""
from dataclasses import asdict
import json
import sys
from threading import RLock


class Recorder:
    def __init__(self, stream=None):
        self.stream = stream if stream is not None else sys.stdout
        self._predictions = {}
        self._sequence = 0
        self._lock = RLock()

    def emit(self, event, scope, **fields):
        with self._lock:
            self._sequence += 1
            record = dict(event=event, scope=scope, sequence=self._sequence, **fields)
            self.stream.write(json.dumps(record, ensure_ascii=False) + '\n')
            self.stream.flush()

    def prediction(self, scope, prediction):
        with self._lock:
            if scope in self._predictions:
                raise ValueError('Initial prediction already recorded')
            self.emit('task_prediction', scope, **asdict(prediction))
            self._predictions[scope] = prediction

    def initial(self, scope):
        return self._predictions[scope]
