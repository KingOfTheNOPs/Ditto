import base64
from mythic_container.MythicCommandBase import *
from mythic_container.MythicRPC import *

from .coffexec import COFF_EXTENSIONS, fetch_mythic_file_contents, search_mythic_file


def safe_get_arg(taskData: PTTaskMessageAllData, name: str, default=None):
    try:
        value = taskData.args.get_arg(name)
    except Exception:
        return default
    return default if value is None else value


class RegisterCoffArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = [
            CommandParameter(
                name="coff_file",
                cli_name="File",
                display_name="COFF File",
                type=ParameterType.File,
                description="COFF/BOF object file to cache in the extension.",
                parameter_group_info=[ParameterGroupInfo(required=True, group_name="Upload", ui_position=1)],
            ),
            CommandParameter(
                name="existing_coff",
                cli_name="Existing",
                display_name="Existing COFF",
                type=ParameterType.ChooseOne,
                dynamic_query_function=self.get_files,
                description="Previously uploaded Mythic file to cache in the extension.",
                parameter_group_info=[ParameterGroupInfo(required=True, group_name="Existing", ui_position=1)],
            ),
            CommandParameter(
                name="name",
                cli_name="Name",
                display_name="Cache Name",
                type=ParameterType.String,
                description="Optional cache name. Defaults to the uploaded filename.",
                default_value="",
                parameter_group_info=[
                    ParameterGroupInfo(required=False, group_name="Upload", ui_position=2),
                    ParameterGroupInfo(required=False, group_name="Existing", ui_position=2),
                ],
            ),
        ]

    async def get_files(self, inputMsg: PTRPCDynamicQueryFunctionMessage) -> PTRPCDynamicQueryFunctionMessageResponse:
        file_response = PTRPCDynamicQueryFunctionMessageResponse(Success=False)
        response = await SendMythicRPCFileSearch(MythicRPCFileSearchMessage(
            CallbackID=inputMsg.Callback,
            LimitByCallback=False,
            Filename="",
        ))
        if not response.Success:
            file_response.Error = response.Error
            return file_response

        choices = []
        for entry in response.Files:
            filename = entry.Filename
            if filename not in choices and filename.lower().endswith(COFF_EXTENSIONS):
                choices.append(filename)
        file_response.Success = True
        file_response.Choices = choices
        return file_response

    async def parse_arguments(self):
        command_line = self.command_line.strip()
        if not command_line:
            raise ValueError("register_coff requires the modal file picker or JSON arguments")
        if command_line[0] != "{":
            raise ValueError("register_coff requires JSON/modal input so Mythic can provide a file id")
        self.load_args_from_json_string(command_line)


class RegisterCoffCommand(CommandBase):
    cmd = "register_coff"
    needs_admin = False
    help_cmd = "register_coff (modal popup)"
    description = "Cache an uploaded COFF/BOF in the extension for later coffexec tasking."
    version = 1
    author = "@kingofthenops"
    attackmapping = ["T1106"]
    argument_class = RegisterCoffArguments
    attributes = CommandAttributes(spawn_and_injectable=False, supported_os=[SupportedOS.Windows])

    async def create_go_tasking(self, taskData: PTTaskMessageAllData) -> PTTaskCreateTaskingMessageResponse:
        group_name = taskData.args.get_parameter_group_name()
        existing_name = (safe_get_arg(taskData, "existing_coff", "") or "").strip()
        upload_file_id = safe_get_arg(taskData, "coff_file", "") or safe_get_arg(taskData, "bof_file", "") or ""

        if existing_name:
            group_name = "Existing"
        elif upload_file_id:
            group_name = "Upload"

        if group_name == "Existing":
            filename = existing_name
            file_meta = await search_mythic_file(taskData.Task.ID, filename=filename)
            file_id = getattr(file_meta, "AgentFileId", None) or getattr(file_meta, "AgentFileID", "")
            try:
                taskData.args.remove_arg("existing_coff")
            except Exception:
                pass
        else:
            file_id = upload_file_id
            if not file_id:
                return PTTaskCreateTaskingMessageResponse(
                    TaskID=taskData.Task.ID,
                    Success=False,
                    Error="register_coff requires existing_coff or coff_file",
                )
            file_meta = await search_mythic_file(taskData.Task.ID, agent_file_id=file_id)
            for arg_name in ("coff_file", "bof_file"):
                try:
                    taskData.args.remove_arg(arg_name)
                except Exception:
                    pass

        file_contents = await fetch_mythic_file_contents(file_id)
        cache_name = (safe_get_arg(taskData, "name", "") or "").strip() or file_meta.Filename
        group_info = [ParameterGroupInfo(required=True, group_name=group_name, ui_position=1)]
        for arg_name, arg_value in (
            ("name", cache_name),
            ("filename", file_meta.Filename),
            ("file_id", file_id),
            ("size", len(file_contents)),
            ("coff_b64", base64.b64encode(file_contents).decode("ascii")),
        ):
            taskData.args.add_arg(arg_name, arg_value, parameter_group_info=group_info)

        return PTTaskCreateTaskingMessageResponse(
            TaskID=taskData.Task.ID,
            Success=True,
            DisplayParams=f"{cache_name} ({len(file_contents)} bytes)",
        )

    async def process_response(self, task: PTTaskMessageAllData, response: any) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
