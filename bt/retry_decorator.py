"""Honest grasp-retry decorator for the FoldBot behavior tree (item 8, first half).

This is the tree's single retry decorator: 2026-10-14 the silent
py_trees.decorators.Retry in bt/pick_subtree.py's GraspWithRetry was
replaced with it (item 8 cleanup), so every retry path now counts
attempts, logs honestly, and supports the on_retry re-observe hook.

Why it exists (the built-in Retry retries silently and exposes no
attempt count; there is no hook to re-observe between attempts; when
it gives up, nothing says so in the logs):
  - the built-in retries silently and exposes no attempt count;
  - there is no hook to re-observe between attempts;
  - when it gives up, nothing says so in the logs.

RetryWithLog keeps the same semantics (retry the child on FAILURE, pass
SUCCESS/RUNNING through) but:
  - counts attempts honestly (attempts_used: attempts that ran to completion),
  - logs every failed attempt at INFO and the give-up at WARNING,
  - calls an optional on_retry(failures_so_far) hook before each re-attempt
    so the real robot can re-run perception and refresh the grasp pose
    (mock default: None = re-run the same child again),
  - returns FAILURE only after max_attempts completed attempts — it never
    reports success it did not observe.
"""
import py_trees


class RetryWithLog(py_trees.decorators.Decorator):
    """Retry a child behaviour on FAILURE up to max_attempts times.

    Args:
        name: node name.
        child: the behaviour/subtree to retry.
        max_attempts: total attempts allowed (>= 1). 1 = no retry, single shot.
        on_retry: optional callable(failures_so_far) invoked before each
            re-attempt. Real robot: re-observe the scene and update the
            child's grasp targets; it must RE-OBSERVE, never invent a pose.
    """

    def __init__(self, name, child, max_attempts=3, on_retry=None):
        if max_attempts < 1:
            raise ValueError(f"max_attempts must be >= 1, got {max_attempts}")
        if on_retry is not None and not callable(on_retry):
            raise TypeError("on_retry must be callable or None")
        super().__init__(name=name, child=child)
        self.max_attempts = max_attempts
        self.on_retry = on_retry
        self._failures = 0
        self._succeeded = False

    def initialise(self):
        self._failures = 0
        self._succeeded = False

    @property
    def attempts_used(self):
        """Number of attempts that ran to completion (success or failure)."""
        return self._failures + (1 if self._succeeded else 0)

    def update(self):
        st = self.decorated.status
        if st == py_trees.common.Status.SUCCESS:
            self._succeeded = True
            self.feedback_message = (
                f"succeeded on attempt {self.attempts_used}/{self.max_attempts}")
            return py_trees.common.Status.SUCCESS
        if st == py_trees.common.Status.RUNNING:
            self.feedback_message = (
                f"attempt {self._failures + 1}/{self.max_attempts} running")
            return py_trees.common.Status.RUNNING
        # Child FAILED this attempt. py_trees' Decorator.tick() re-ticks the
        # child next tick (its status is FAILURE, not RUNNING, so its
        # initialise() runs again) — the attempt below restarts it cleanly.
        self._failures += 1
        if self._failures >= self.max_attempts:
            self.feedback_message = (
                f"gave up after {self._failures} attempts")
            self.logger.warning(
                f"[{self.name}] grasp failed {self._failures}/"
                f"{self.max_attempts} attempts — giving up (FAILURE)")
            return py_trees.common.Status.FAILURE
        self.feedback_message = (
            f"attempt {self._failures}/{self.max_attempts} failed — retrying")
        self.logger.info(
            f"[{self.name}] attempt {self._failures}/{self.max_attempts} "
            f"failed — retrying")
        if self.on_retry is not None:
            self.on_retry(self._failures)
        return py_trees.common.Status.RUNNING
