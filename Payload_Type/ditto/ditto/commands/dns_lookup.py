from mythic_container.MythicCommandBase import *


class DnsLookupArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = [
            CommandParameter(
                name="name",
                type=ParameterType.String,
                description="Hostname to resolve.",
                parameter_group_info=[ParameterGroupInfo(required=True)],
            ),
            CommandParameter(
                name="type",
                type=ParameterType.String,
                description="DNS record type such as A, AAAA, TXT, MX, or CNAME.",
                parameter_group_info=[ParameterGroupInfo(required=False)],
                default_value="A",
            ),
            CommandParameter(
                name="resolver",
                type=ParameterType.String,
                description="Optional DoH resolver alias or URL. Defaults to google.",
                parameter_group_info=[ParameterGroupInfo(required=False)],
                default_value="google",
            ),
        ]

    async def parse_arguments(self):
        if len(self.command_line) == 0:
            raise ValueError("Must supply a hostname to resolve")

        if self.command_line[0] == "{":
            self.load_args_from_json_string(self.command_line)
            return

        parts = self.command_line.split()
        self.add_arg("name", parts[0])
        if len(parts) > 1:
            self.add_arg("type", parts[1].upper())
        if len(parts) > 2:
            self.add_arg("resolver", parts[2])


class DnsLookupCommand(CommandBase):
    cmd = "dns_lookup"
    needs_admin = False
    help_cmd = "dns_lookup <hostname> [type] [resolver]"
    description = "Resolve a hostname from the extension runtime, using chrome.dns when available and DoH otherwise."
    version = 1
    author = "@kingofthenops"
    attackmapping = ["T1016"]
    argument_class = DnsLookupArguments
    attributes = CommandAttributes(spawn_and_injectable=False)

    async def create_go_tasking(self, taskData: PTTaskMessageAllData) -> PTTaskCreateTaskingMessageResponse:
        name = taskData.args.get_arg("name")
        record_type = (taskData.args.get_arg("type") or "A").upper()
        resolver = taskData.args.get_arg("resolver") or "google"
        return PTTaskCreateTaskingMessageResponse(
            TaskID=taskData.Task.ID,
            Success=True,
            DisplayParams=f"{name} {record_type} via {resolver}",
        )

    async def process_response(self, task: PTTaskMessageAllData, response: any) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
