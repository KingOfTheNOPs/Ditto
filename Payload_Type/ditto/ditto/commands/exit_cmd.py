from mythic_container.MythicCommandBase import *


class ExitArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = []

    async def parse_arguments(self):
        return


class ExitCommand(CommandBase):
    cmd = "exit"
    needs_admin = False
    help_cmd = "exit"
    description = "Stop the extension polling loop."
    version = 1
    author = "@kingofthenops"
    argument_class = ExitArguments
    supported_ui_features = ["callback_table:exit"]
    attributes = CommandAttributes(
        supported_os=[SupportedOS.Windows],
        builtin=False,
        spawn_and_injectable=False,
    )

    async def create_go_tasking(self, taskData: PTTaskMessageAllData) -> PTTaskCreateTaskingMessageResponse:
        return PTTaskCreateTaskingMessageResponse(
            TaskID=taskData.Task.ID,
            Success=True,
            DisplayParams="",
        )

    async def process_response(self, task: PTTaskMessageAllData, response: any) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
