from mythic_container.MythicCommandBase import *


class IwaStartSocksArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = [
            CommandParameter(
                name="port",
                type=ParameterType.Number,
                description="SOCKS listen port.",
                parameter_group_info=[ParameterGroupInfo(required=False)],
                default_value=38900,
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
        self.add_arg("port", int(command_line))


class IwaStartSocksCommand(CommandBase):
    cmd = "iwa_start_socks"
    needs_admin = False
    help_cmd = "iwa_start_socks [port]"
    description = "Debug only: start the IWA local SOCKS listener through the control WebSocket."
    version = 1
    author = "@kingofthenops"
    attackmapping = []
    argument_class = IwaStartSocksArguments
    attributes = CommandAttributes(spawn_and_injectable=False)

    async def create_go_tasking(self, taskData: PTTaskMessageAllData) -> PTTaskCreateTaskingMessageResponse:
        port = taskData.args.get_arg("port") or 38900
        return PTTaskCreateTaskingMessageResponse(
            TaskID=taskData.Task.ID,
            Success=True,
            DisplayParams=str(port),
        )

    async def process_response(self, task: PTTaskMessageAllData, response: any) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
