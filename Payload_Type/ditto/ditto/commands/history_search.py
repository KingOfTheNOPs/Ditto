from mythic_container.MythicCommandBase import *


class HistorySearchArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = [
            CommandParameter(
                name="text",
                type=ParameterType.String,
                description="History search string",
                parameter_group_info=[ParameterGroupInfo(required=False)],
                default_value="",
            ),
        ]

    async def parse_arguments(self):
        if len(self.command_line) > 0:
            if self.command_line[0] == "{":
                self.load_args_from_json_string(self.command_line)
            else:
                self.add_arg("text", self.command_line)


class HistorySearchCommand(CommandBase):
    cmd = "history_search"
    needs_admin = False
    help_cmd = "history_search [text]"
    description = "Search the browser history."
    version = 1
    author = "@kingofthenops"
    attackmapping = ["T1217"]
    argument_class = HistorySearchArguments
    supported_ui_features = ["browser_history:search"]
    browser_script = BrowserScript(
        script_name="history_search", author="@kingofthenops", for_new_ui=True
    )
    attributes = CommandAttributes(spawn_and_injectable=False)

    async def create_go_tasking(self, taskData: PTTaskMessageAllData) -> PTTaskCreateTaskingMessageResponse:
        return PTTaskCreateTaskingMessageResponse(
            TaskID=taskData.Task.ID,
            Success=True,
            DisplayParams=taskData.args.get_arg("text") or "",
        )

    async def process_response(self, task: PTTaskMessageAllData, response: any) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
