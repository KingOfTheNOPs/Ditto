from mythic_container.MythicCommandBase import *


class IwaStatusArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = [
            CommandParameter(
                name="probe",
                type=ParameterType.Boolean,
                description="Probe the IWA control WebSocket in addition to returning bridge state.",
                parameter_group_info=[ParameterGroupInfo(required=False)],
                default_value=True,
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
        if command_line.lower() in {"false", "no", "0"}:
            self.add_arg("probe", False)


class IwaStatusCommand(CommandBase):
    cmd = "iwa_status"
    needs_admin = False
    help_cmd = "iwa_status [false]"
    description = "Return the IWA bridge state and optionally probe the control WebSocket."
    version = 1
    author = "@kingofthenops"
    attackmapping = []
    argument_class = IwaStatusArguments
    attributes = CommandAttributes(spawn_and_injectable=False)

    async def create_go_tasking(self, taskData: PTTaskMessageAllData) -> PTTaskCreateTaskingMessageResponse:
        probe = taskData.args.get_arg("probe")
        return PTTaskCreateTaskingMessageResponse(
            TaskID=taskData.Task.ID,
            Success=True,
            DisplayParams=f"probe={probe}",
        )

    async def process_response(self, task: PTTaskMessageAllData, response: any) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
