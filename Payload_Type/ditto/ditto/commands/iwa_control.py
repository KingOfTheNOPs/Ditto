from mythic_container.MythicCommandBase import *


class IwaControlArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = [
            CommandParameter(
                name="type",
                type=ParameterType.String,
                description="IWA control command type.",
                parameter_group_info=[ParameterGroupInfo(required=False)],
                default_value="status",
            ),
            CommandParameter(
                name="message",
                type=ParameterType.String,
                description="Optional raw JSON control message object.",
                parameter_group_info=[ParameterGroupInfo(required=False)],
                default_value="",
            ),
            CommandParameter(
                name="control_url",
                type=ParameterType.String,
                description="Optional control WebSocket URL override.",
                parameter_group_info=[ParameterGroupInfo(required=False)],
                default_value="",
            ),
        ]

    async def parse_arguments(self):
        command_line = self.command_line.strip()
        if not command_line:
            return
        if command_line[0] == "{":
            self.load_args_from_json_string(command_line)
            return
        self.add_arg("type", command_line)


class IwaControlCommand(CommandBase):
    cmd = "iwa_control"
    needs_admin = False
    help_cmd = "iwa_control <status|ping|start_socks|stop_socks|logs|tcp_probe|json>"
    description = "Send a raw control message to the IWA WebSocket."
    version = 1
    author = "@kingofthenops"
    attackmapping = []
    argument_class = IwaControlArguments
    attributes = CommandAttributes(spawn_and_injectable=False)

    async def create_go_tasking(self, taskData: PTTaskMessageAllData) -> PTTaskCreateTaskingMessageResponse:
        control_type = taskData.args.get_arg("type") or "status"
        return PTTaskCreateTaskingMessageResponse(
            TaskID=taskData.Task.ID,
            Success=True,
            DisplayParams=control_type,
        )

    async def process_response(self, task: PTTaskMessageAllData, response: any) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
