from mythic_container.MythicCommandBase import *


class IwaPingArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = [
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
        self.add_arg("control_url", command_line)


class IwaPingCommand(CommandBase):
    cmd = "iwa_ping"
    needs_admin = False
    help_cmd = "iwa_ping [ws://127.0.0.1:38899]"
    description = "Ping the IWA control WebSocket through the extension."
    version = 1
    author = "@kingofthenops"
    attackmapping = []
    argument_class = IwaPingArguments
    attributes = CommandAttributes(spawn_and_injectable=False)

    async def create_go_tasking(self, taskData: PTTaskMessageAllData) -> PTTaskCreateTaskingMessageResponse:
        return PTTaskCreateTaskingMessageResponse(
            TaskID=taskData.Task.ID,
            Success=True,
            DisplayParams=taskData.args.get_arg("control_url") or "",
        )

    async def process_response(self, task: PTTaskMessageAllData, response: any) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
