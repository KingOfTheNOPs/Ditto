from mythic_container.MythicCommandBase import *


class ListTabsArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = []

    async def parse_arguments(self):
        return


class ListTabsCommand(CommandBase):
    cmd = "list_tabs"
    needs_admin = False
    help_cmd = "list_tabs"
    description = "List browser tabs visible to the extension."
    version = 1
    author = "@kingofthenops"
    attackmapping = ["T1217"]
    argument_class = ListTabsArguments
    supported_ui_features = ["browser_tabs:list"]
    browser_script = BrowserScript(
        script_name="list_tabs", author="@kingofthenops", for_new_ui=True
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
