from mythic_container.MythicCommandBase import *
from mythic_container.MythicGoRPC import *


class SocksArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = [
            CommandParameter(
                name="action",
                type=ParameterType.ChooseOne,
                choices=["start", "stop", "status"],
                description="Start, stop, or inspect the Mythic/IWA SOCKS bridge.",
                parameter_group_info=[ParameterGroupInfo(required=False, ui_position=1)],
                default_value="start",
            ),
            CommandParameter(
                name="port",
                type=ParameterType.Number,
                description="SOCKS listen port on the Mythic server.",
                parameter_group_info=[ParameterGroupInfo(required=False, ui_position=2)],
                default_value=1080,
            ),
            CommandParameter(
                name="control_url",
                type=ParameterType.String,
                description="IWA control WebSocket URL.",
                parameter_group_info=[ParameterGroupInfo(required=False, ui_position=3)],
                default_value="",
            ),
        ]

    async def parse_arguments(self):
        command_line = self.command_line.strip()
        if not command_line:
            return
        if command_line[0] == "{":
            self.load_args_from_json_string(command_line)
            return

        parts = command_line.split()
        if parts[0].isdigit():
            self.add_arg("action", "start")
            self.add_arg("port", int(parts[0]))
            return

        self.add_arg("action", parts[0].lower())
        if len(parts) > 1 and parts[1].isdigit():
            self.add_arg("port", int(parts[1]))
        if len(parts) > 2:
            self.add_arg("control_url", parts[2])


class SocksCommand(CommandBase):
    cmd = "socks"
    needs_admin = False
    help_cmd = "socks [start|stop|status] [mythic_port] [ws://127.0.0.1:38899]"
    description = "Start Mythic SOCKS and bridge proxy frames through the extension to the IWA Direct Sockets relay."
    version = 1
    author = "@kingofthenops"
    attackmapping = ["T1090"]
    argument_class = SocksArguments
    attributes = CommandAttributes(spawn_and_injectable=False)

    async def create_go_tasking(self, taskData: PTTaskMessageAllData) -> PTTaskCreateTaskingMessageResponse:
        action = (taskData.args.get_arg("action") or "start").lower()
        port = int(taskData.args.get_arg("port") or 1080)
        response = PTTaskCreateTaskingMessageResponse(
            TaskID=taskData.Task.ID,
            Success=True,
            DisplayParams=f"{action} port={port}",
        )

        if action == "start":
            proxy_resp = await SendMythicRPCProxyStartCommand(MythicRPCProxyStartMessage(
                TaskID=taskData.Task.ID,
                LocalPort=port,
                PortType="socks",
            ))
            if not getattr(proxy_resp, "Success", False):
                response.Success = False
                response.Error = getattr(proxy_resp, "Error", "failed to start SOCKS proxy")
        elif action == "stop":
            proxy_resp = await SendMythicRPCProxyStopCommand(MythicRPCProxyStopMessage(
                TaskID=taskData.Task.ID,
                Port=port,
                PortType="socks",
            ))
            if not getattr(proxy_resp, "Success", False):
                response.Success = False
                response.Error = getattr(proxy_resp, "Error", "failed to stop SOCKS proxy")
        elif action != "status":
            response.Success = False
            response.Error = "action must be start, stop, or status"

        return response

    async def process_response(self, task: PTTaskMessageAllData, response: any) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
