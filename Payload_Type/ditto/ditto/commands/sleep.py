from mythic_container.MythicCommandBase import *


class SleepArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = [
            CommandParameter(
                name="interval",
                type=ParameterType.Number,
                description="Polling interval in seconds.",
                parameter_group_info=[ParameterGroupInfo(required=True)],
                default_value=30,
            ),
        ]

    async def parse_arguments(self):
        if len(self.command_line) == 0:
            raise ValueError("Must supply a polling interval in seconds")

        if self.command_line[0] == "{":
            self.load_args_from_json_string(self.command_line)
            return

        self.add_arg("interval", int(self.command_line))


class SleepCommand(CommandBase):
    cmd = "sleep"
    needs_admin = False
    help_cmd = "sleep <seconds>"
    description = "Update the extension polling interval without rebuilding."
    version = 1
    author = "@kingofthenops"
    attackmapping = []
    argument_class = SleepArguments
    attributes = CommandAttributes(spawn_and_injectable=False)

    async def create_go_tasking(self, taskData: PTTaskMessageAllData) -> PTTaskCreateTaskingMessageResponse:
        interval = int(taskData.args.get_arg("interval"))
        return PTTaskCreateTaskingMessageResponse(
            TaskID=taskData.Task.ID,
            Success=interval > 0,
            DisplayParams=f"{interval}s",
            Error="" if interval > 0 else "Sleep interval must be greater than 0",
        )

    async def process_response(self, task: PTTaskMessageAllData, response: any) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
