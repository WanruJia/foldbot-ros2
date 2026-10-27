"""ROS 2 transport for configured robot primitive action servers."""
import json

from execution.actions import ActionBehaviour


class RosBackend:
    """Share one primitive client and inhibit motion after an uncertain stop."""

    def __init__(self, node, action_name="execute_primitive", frame_id="board",
                 timeout=60.0, client=None, action_type=None):
        if client is None:
            from rclpy.action import ActionClient
            from foldbot_interfaces.action import ExecutePrimitive

            action_type = ExecutePrimitive
            client = ActionClient(node, action_type, action_name)
        self.client = client
        self.action_type = action_type
        self.frame_id = frame_id
        self.timeout = timeout
        self.fault = False

    def _inhibit(self):
        self.fault = True

    def action(self, name, context, on_success=None):
        def goal():
            if self.fault:
                raise RuntimeError("motion inhibited: previous stop is unconfirmed")
            payload = context() if callable(context) else context
            request = self.action_type.Goal()
            request.command = name
            request.frame_id = self.frame_id
            request.context_json = json.dumps(payload, allow_nan=False)
            return request

        return ActionBehaviour(name, self.client, goal, timeout=self.timeout,
                               on_success=on_success,
                               on_uncertain=self._inhibit)