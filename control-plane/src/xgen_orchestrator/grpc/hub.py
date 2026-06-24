"""연결 허브 — node_id → outbound 큐. HTTP에서 만든 명령을 해당 노드의 stream으로 push.

CP가 단일 프로세스라 인메모리. 다중 CP(HA)에서는 공유 버스로 승격(14-future-and-residuals).
"""
from __future__ import annotations

import queue
import threading


class Hub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._queues: dict[str, queue.Queue] = {}

    def register(self, node_id: str) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=256)
        with self._lock:
            self._queues[node_id] = q  # 재연결 시 최신 연결로 대체
        return q

    def unregister(self, node_id: str, q: queue.Queue) -> None:
        with self._lock:
            if self._queues.get(node_id) is q:
                del self._queues[node_id]

    def send(self, node_id: str, server_msg) -> bool:
        with self._lock:
            q = self._queues.get(node_id)
        if q is None:
            return False
        try:
            q.put_nowait(server_msg)
            return True
        except queue.Full:
            return False


hub = Hub()
