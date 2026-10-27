"""Non-blocking action lifecycle, independent of ROS imports."""
import math
import time

import py_trees


class ActionBehaviour(py_trees.behaviour.Behaviour):
    """Run one asynchronous command and cancel it when interrupted."""

    def __init__(self, name, client, goal_factory, timeout=60.0,
                 on_success=None, clock=time.monotonic, on_uncertain=None):
        super().__init__(name)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive")
        self.client = client
        self.goal_factory = goal_factory
        self.timeout = timeout
        self.on_success = on_success
        self.on_uncertain = on_uncertain
        self.clock = clock
        self._attempt = None

    def initialise(self):
        self._started = self.clock()
        self._attempt = {"send": None, "handle": None, "result": None,
                         "cancelled": False}

    def _cancel(self, attempt):
        if attempt["cancelled"]:
            return
        attempt["cancelled"] = True
        handle = attempt["handle"]
        result = attempt["result"]
        uncertain = (attempt["send"] is not None and
                     (handle is None or (handle.accepted and
                      (result is None or not result.done()))))
        if uncertain and self.on_uncertain is not None:
            self.on_uncertain()
        if handle is not None and handle.accepted:
            if result is None or not result.done():
                handle.cancel_goal_async()

    @staticmethod
    def _accepted(future, attempt):
        try:
            handle = future.result()
            attempt["handle"] = handle
            if handle.accepted:
                if attempt["cancelled"]:
                    handle.cancel_goal_async()
                else:
                    attempt["result"] = handle.get_result_async()
        except Exception as error:
            attempt["error"] = error

    def update(self):
        attempt = self._attempt
        try:
            if self.clock() - self._started >= self.timeout:
                self._cancel(attempt)
                self.feedback_message = "command timed out"
                return py_trees.common.Status.FAILURE
            if attempt["send"] is None:
                if not self.client.server_is_ready():
                    return py_trees.common.Status.RUNNING
                future = self.client.send_goal_async(self.goal_factory())
                attempt["send"] = future
                future.add_done_callback(
                    lambda completed: self._accepted(completed, attempt))
            if "error" in attempt:
                raise attempt["error"]
            handle = attempt["handle"]
            if handle is not None and not handle.accepted:
                self.feedback_message = "command rejected"
                return py_trees.common.Status.FAILURE
            future = attempt["result"]
            if future is None or not future.done():
                return py_trees.common.Status.RUNNING
            response = future.result()
            self.feedback_message = response.result.message
            if response.status != 4 or not response.result.success:
                return py_trees.common.Status.FAILURE
            if self.on_success is not None:
                self.on_success()
            return py_trees.common.Status.SUCCESS
        except Exception as error:
            self.feedback_message = str(error)
            if attempt["send"] is not None and self.on_uncertain is not None:
                self.on_uncertain()
            self._cancel(attempt)
            return py_trees.common.Status.FAILURE

    def terminate(self, new_status):
        if self._attempt is not None and new_status != py_trees.common.Status.SUCCESS:
            if not self._attempt["cancelled"]:
                self._cancel(self._attempt)


def bind_primitives(root, backend, context, path=()):
    """Replace primitive leaves while preserving sequences and retry decorators."""
    path = (*path, root.name)
    for child in list(root.children):
        if child.children:
            bind_primitives(child, backend, context, path)
        else:
            root.replace_child(child, backend.action(
                child.name, {**context, "path": list((*path, child.name))}))
    return root