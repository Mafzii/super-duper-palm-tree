"""Thread-safe priority URL queue with lazy-deletion re-prioritization."""
import heapq
import threading


class UrlQueue:
    """
    Priority queue for URLs. Lower priority value = higher urgency.
    Supports re-prioritization via lazy deletion: push new (score, url),
    skip stale entries on pop (where heap score != current dict score).
    """

    def __init__(self):
        self._heap: list[tuple[float, str]] = []
        self._url_to_priority: dict[str, float] = {}
        self._seen: set[str] = set()
        self._lock = threading.Lock()

    def enqueue(self, url: str, priority: float = 0.0) -> bool:
        """Add URL if not seen. Returns True if added."""
        with self._lock:
            if url in self._seen:
                return False
            self._seen.add(url)
            self._url_to_priority[url] = priority
            heapq.heappush(self._heap, (priority, url))
            return True

    def requeue(self, url: str, new_priority: float) -> None:
        """Update priority of a URL still in the queue (not yet dequeued)."""
        with self._lock:
            if url not in self._url_to_priority:
                return
            self._url_to_priority[url] = new_priority
            heapq.heappush(self._heap, (new_priority, url))

    def dequeue(self) -> tuple[str, float] | None:
        """Pop the highest-priority (lowest value) URL. Returns None if empty."""
        with self._lock:
            while self._heap:
                priority, url = heapq.heappop(self._heap)
                current = self._url_to_priority.get(url)
                if current is not None and current == priority:
                    del self._url_to_priority[url]
                    return url, priority
            return None

    def size(self) -> int:
        with self._lock:
            return len(self._url_to_priority)

    def seen_count(self) -> int:
        with self._lock:
            return len(self._seen)

    def is_seen(self, url: str) -> bool:
        with self._lock:
            return url in self._seen

    def get_priority(self, url: str) -> float | None:
        """Return current priority of a queued URL, or None if already dequeued."""
        with self._lock:
            return self._url_to_priority.get(url)
