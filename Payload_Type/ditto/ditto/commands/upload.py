from mythic_container.MythicCommandBase import *
from mythic_container.MythicRPC import *


async def search_mythic_file(task_id: int, agent_file_id: str):
    try:
        request = MythicRPCFileSearchMessage(TaskID=task_id, AgentFileID=agent_file_id)
    except TypeError:
        request = MythicRPCFileSearchMessage(TaskID=task_id, AgentFileId=agent_file_id)
    response = await SendMythicRPCFileSearch(request)
    if not response.Success:
        raise ValueError(response.Error)
    if len(response.Files) == 0:
        raise ValueError("matching Mythic file was not found")
    return response.Files[0]


def file_filename(file_meta) -> str:
    return (
        getattr(file_meta, "Filename", None)
        or getattr(file_meta, "filename", None)
        or getattr(file_meta, "Name", None)
        or getattr(file_meta, "name", None)
        or "upload.bin"
    )


def set_or_add_arg(args, name: str, value, arg_type=ParameterType.String):
    try:
        args.set_arg(name, value)
    except Exception:
        args.add_arg(name, value, type=arg_type)


class UploadArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = [
            CommandParameter(
                name="path",
                type=ParameterType.String,
                cli_name="Path",
                display_name="Destination path",
                description="Destination path on the target. If omitted, defaults to the uploaded filename.",
                parameter_group_info=[ParameterGroupInfo(required=False, ui_position=2)],
            ),
            CommandParameter(
                name="file",
                type=ParameterType.File,
                cli_name="File",
                display_name="File",
                description="File to upload to the target.",
                parameter_group_info=[ParameterGroupInfo(required=True, ui_position=1)],
            ),
            CommandParameter(
                name="create_dirs",
                type=ParameterType.Boolean,
                description="Create missing parent directories.",
                parameter_group_info=[ParameterGroupInfo(required=False, ui_position=3)],
                default_value=True,
            ),
        ]

    async def parse_arguments(self):
        command_line = self.command_line.strip()
        if not command_line:
            raise ValueError("upload requires the Mythic file picker")
        if command_line[0] == "{":
            self.load_args_from_json_string(command_line)
            try:
                remote_path = self.get_arg("remote_path")
            except Exception:
                remote_path = None
            if remote_path and not self.get_arg("path"):
                set_or_add_arg(self, "path", remote_path)
            return
        raise ValueError("upload requires JSON or the Mythic modal file picker")

    async def parse_dictionary(self, dictionary_arguments):
        self.load_args_from_dictionary(dictionary_arguments)
        if "remote_path" in dictionary_arguments and "path" not in dictionary_arguments:
            self.add_arg("path", dictionary_arguments["remote_path"])
        elif "full_path" in dictionary_arguments and "path" not in dictionary_arguments:
            self.add_arg("path", dictionary_arguments["full_path"])


class UploadCommand(CommandBase):
    cmd = "upload"
    needs_admin = False
    help_cmd = "upload (modal file picker)"
    description = "Upload a Mythic file to disk through the native messaging host."
    version = 2
    author = "@kingofthenops"
    attackmapping = ["T1105"]
    argument_class = UploadArguments
    is_file_upload = True
    supported_ui_features = ["file_browser:upload"]
    browser_script = BrowserScript(
        script_name="upload", author="@kingofthenops", for_new_ui=True
    )
    attributes = CommandAttributes(spawn_and_injectable=False)

    async def create_go_tasking(self, taskData: PTTaskMessageAllData) -> PTTaskCreateTaskingMessageResponse:
        path = taskData.args.get_arg("path") or ""
        file_id = taskData.args.get_arg("file") or ""
        file_name = "upload.bin"
        if file_id:
            file_meta = await search_mythic_file(taskData.Task.ID, file_id)
            file_name = file_filename(file_meta)
            taskData.args.add_arg("file_name", file_name, type=ParameterType.String)
        if not path:
            path = file_name
            set_or_add_arg(taskData.args, "path", path)
        return PTTaskCreateTaskingMessageResponse(
            TaskID=taskData.Task.ID,
            Success=True,
            DisplayParams=f"{file_name} -> {path}",
        )

    async def process_response(self, task: PTTaskMessageAllData, response: any) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
