from mythic_container.MythicCommandBase import *


class LsArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = [
            CommandParameter(
                name="path",
                type=ParameterType.String,
                description="Directory path to list.",
                parameter_group_info=[ParameterGroupInfo(required=False, ui_position=1)],
                default_value=".",
            )
        ]

    async def parse_arguments(self):
        command_line = self.command_line.strip()
        if not command_line:
            return
        if command_line[0] == "{":
            self.load_args_from_json_string(command_line)
            return
        parts = command_line.split(maxsplit=1)
        self.add_arg("path", parts[0])


class LsCommand(CommandBase):
    cmd = "ls"
    needs_admin = False
    help_cmd = "ls [path]"
    description = "List a directory through the native messaging host."
    version = 1
    author = "@kingofthenops"
    attackmapping = ["T1083"]
    argument_class = LsArguments
    supported_ui_features = ["file_browser:list"]
    browser_script = BrowserScript(
        script_name="ls", author="@kingofthenops", for_new_ui=True
    )
    attributes = CommandAttributes(spawn_and_injectable=False)

    async def create_go_tasking(self, taskData: PTTaskMessageAllData) -> PTTaskCreateTaskingMessageResponse:
        path = taskData.args.get_arg("path") or "."
        return PTTaskCreateTaskingMessageResponse(
            TaskID=taskData.Task.ID,
            Success=True,
            DisplayParams=path,
        )

    async def process_response(self, task: PTTaskMessageAllData, response: any) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
