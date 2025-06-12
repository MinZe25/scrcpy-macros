import queue
import threading


class NonBlockingStreamReader:
    def __init__(self, stream):
        self._stream = stream
        self._queue = queue.Queue()

        def _populateQueue(stream, q):
            # Read until EOF
            for line in iter(stream.readline, b''):
                if line:  # Ensure line is not empty before putting in queue
                    q.put(line)
            stream.close()

        self._thread = threading.Thread(target=_populateQueue, args=(self._stream, self._queue))
        self._thread.daemon = True  # Thread dies with the main program
        self._thread.start()

    def readline(self):
        try:
            # Get line from queue, non-blocking
            return self._queue.get(block=False)
        except queue.Empty:
            return None
