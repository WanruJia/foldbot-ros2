"""Fresh-frame gating independent of ROS image conversion."""
import math
import time


class FreshFrameSource:
    """Accept only a recent image exposed after the current capture request."""

    def __init__(self, save, ros_now_ns, timeout=5.0, max_age=1.0,
                 clock=time.monotonic):
        if any(not math.isfinite(value) or value <= 0
               for value in (timeout, max_age)):
            raise ValueError("camera timeout and max_age must be positive")
        self.save = save
        self.ros_now_ns = ros_now_ns
        self.timeout = timeout
        self.max_age_ns = int(max_age * 1_000_000_000)
        self.clock = clock
        self._waiting = False

    def request(self):
        self._after_ns = self.ros_now_ns()
        self._started = self.clock()
        self._frame = None
        self._error = None
        self._waiting = True

    def receive(self, message):
        if not self._waiting:
            return
        stamp = message.header.stamp
        stamp_ns = stamp.sec * 1_000_000_000 + stamp.nanosec
        age_ns = self.ros_now_ns() - stamp_ns
        if stamp_ns <= self._after_ns or not 0 <= age_ns <= self.max_age_ns:
            return
        self._waiting = False
        try:
            self._frame = self.save(message)
        except Exception as error:
            self._error = str(error)

    def poll(self):
        if self._error is not None:
            raise ValueError(self._error)
        if self._frame is not None:
            return self._frame
        if self.clock() - self._started >= self.timeout:
            self._waiting = False
            raise TimeoutError("no fresh camera frame before capture timeout")
        return None