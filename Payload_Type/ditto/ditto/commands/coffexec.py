import base64
from mythic_container.MythicCommandBase import *
from mythic_container.MythicRPC import *


COFF_EXTENSIONS = (".o", ".obj", ".coff", ".bof")


def _extract_file_contents(rpc_response) -> bytes | None:
    candidates = [
        getattr(rpc_response, "Content", None),
        getattr(rpc_response, "content", None),
        getattr(rpc_response, "FileContents", None),
        getattr(rpc_response, "file_contents", None),
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        if isinstance(candidate, bytes):
            return candidate
        if isinstance(candidate, bytearray):
            return bytes(candidate)
        if isinstance(candidate, str):
            try:
                return base64.b64decode(candidate, validate=True)
            except Exception:
                return candidate.encode("utf-8")
    return None


async def fetch_mythic_file_contents(agent_file_id: str) -> bytes:
    try:
        request = MythicRPCFileGetContentMessage(AgentFileId=agent_file_id)
    except TypeError:
        request = MythicRPCFileGetContentMessage(AgentFileID=agent_file_id)

    rpc_response = await SendMythicRPCFileGetContent(request)
    if getattr(rpc_response, "Success", True) is False:
        raise ValueError(getattr(rpc_response, "Error", "failed to fetch file content"))

    contents = _extract_file_contents(rpc_response)
    if not contents:
        raise ValueError("uploaded COFF was empty or unreadable")
    return contents


async def search_mythic_file(task_id: int, agent_file_id: str = "", filename: str = ""):
    if agent_file_id:
        request = MythicRPCFileSearchMessage(TaskID=task_id, AgentFileID=agent_file_id)
    else:
        request = MythicRPCFileSearchMessage(TaskID=task_id, Filename=filename, MaxResults=1)
    response = await SendMythicRPCFileSearch(request)
    if not response.Success:
        raise ValueError(response.Error)
    if len(response.Files) == 0:
        raise ValueError("matching Mythic file was not found")
    return response.Files[0]


def normalize_coff_arg(kind: str, value):
    normalized = str(kind).strip()
    value_text = str(value).strip().strip("'").strip('"')
    lowered = normalized.lower()
    if lowered in {"int16", "-s", "s", "short"}:
        return {"type": "int16", "value": int(value_text)}
    if lowered in {"int32", "-i", "i", "int", "dword"}:
        return {"type": "int32", "value": int(value_text)}
    if normalized in {"-Z", "Z"} or lowered in {"wchar", "z_wide", "wstr", "wstring", "wide", "utf16", "utf16le"}:
        return {"type": "wchar", "value": value_text}
    if lowered in {"string", "-z", "z", "str"}:
        return {"type": "string", "value": value_text}
    if lowered in {"base64", "-b", "b", "bytes", "bin"}:
        return {"type": "base64", "value": value_text}
    raise ValueError(f"unknown COFF argument type: {kind}")


def parse_coff_argument_tokens(values) -> list[dict]:
    parsed = []
    for raw_value in values:
        for token in str(raw_value).split():
            if not token:
                continue
            if ":" not in token:
                raise ValueError(f"COFF argument requires type:value format: {token}")
            kind, value = token.split(":", 1)
            parsed.append(normalize_coff_arg(kind, value))
    return parsed


def normalize_typed_args(value) -> list[dict]:
    if not value:
        return []
    if isinstance(value, str):
        return parse_coff_argument_tokens([value])
    if all(isinstance(entry, str) for entry in value):
        return parse_coff_argument_tokens(value)

    normalized = []
    for entry in value:
        if isinstance(entry, dict):
            kind = entry.get("type") or entry.get("t")
            item_value = entry.get("value") if "value" in entry else entry.get("v")
            normalized.append(normalize_coff_arg(kind, item_value))
        elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
            normalized.append(normalize_coff_arg(entry[0], entry[1]))
        else:
            raise ValueError(f"invalid COFF argument entry: {entry}")
    return normalized


def typed_args_display(typed_args: list[dict]) -> str:
    if not typed_args:
        return ""
    rendered = []
    for entry in typed_args:
        value = entry["value"]
        if isinstance(value, str) and " " in value:
            value = f'"{value}"'
        rendered.append(f"{entry['type']}:{value}")
    return " -Arguments " + " ".join(rendered)


def safe_get_arg(taskData: PTTaskMessageAllData, name: str, default=None):
    try:
        value = taskData.args.get_arg(name)
    except Exception:
        return default
    return default if value is None else value


class CoffexecArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = [
            CommandParameter(
                name="coff_name",
                cli_name="Coff",
                display_name="Registered COFF",
                type=ParameterType.ChooseOne,
                dynamic_query_function=self.get_files,
                description="Registered COFF/BOF name, for example dir.x64.o.",
                parameter_group_info=[ParameterGroupInfo(required=True, group_name="Registered", ui_position=1)],
            ),
            CommandParameter(
                name="bof_file",
                display_name="New BOF",
                type=ParameterType.File,
                description="Upload and execute a new BOF once.",
                parameter_group_info=[ParameterGroupInfo(required=True, group_name="New", ui_position=1)],
            ),
            CommandParameter(
                name="function",
                cli_name="Function",
                display_name="Function",
                type=ParameterType.String,
                description="BOF entrypoint.",
                default_value="go",
                parameter_group_info=[
                    ParameterGroupInfo(required=False, group_name="Registered", ui_position=2),
                    ParameterGroupInfo(required=False, group_name="New", ui_position=2),
                ],
            ),
            CommandParameter(
                name="timeout",
                cli_name="Timeout",
                display_name="Timeout",
                type=ParameterType.Number,
                description="Requested COFF timeout in seconds. Reserved for host-side timeout support.",
                default_value=30,
                parameter_group_info=[
                    ParameterGroupInfo(required=False, group_name="Registered", ui_position=3),
                    ParameterGroupInfo(required=False, group_name="New", ui_position=3),
                ],
            ),
            CommandParameter(
                name="coff_arguments",
                cli_name="Arguments",
                display_name="Arguments",
                type=ParameterType.TypedArray,
                default_value=[],
                choices=["int16", "int32", "string", "wchar", "base64"],
                description="Apollo-style BOF args: int16:1 int32:2 string:abc wchar:C:\\\\ base64:AA==",
                typedarray_parse_function=self.get_arguments,
                parameter_group_info=[
                    ParameterGroupInfo(required=False, group_name="Registered", ui_position=4),
                    ParameterGroupInfo(required=False, group_name="New", ui_position=4),
                ],
            ),
        ]

    async def get_arguments(self, arguments: PTRPCTypedArrayParseFunctionMessage) -> PTRPCTypedArrayParseFunctionMessageResponse:
        try:
            parsed = normalize_typed_args(arguments.InputArray)
            return PTRPCTypedArrayParseFunctionMessageResponse(
                Success=True,
                TypedArray=[[entry["type"], entry["value"]] for entry in parsed],
            )
        except Exception as exc:
            return PTRPCTypedArrayParseFunctionMessageResponse(Success=False, Error=str(exc))

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
            raise ValueError("coffexec requires a registered COFF name or New BOF upload")
        if command_line[0] == "{":
            self.load_args_from_json_string(command_line)
            return

        parts = command_line.split()
        self.add_arg("coff_name", parts[0])
        if len(parts) > 1 and ":" not in parts[1]:
            self.add_arg("function", parts[1])
            arg_tokens = parts[2:]
        else:
            arg_tokens = parts[1:]
        if arg_tokens:
            self.add_arg("coff_arguments", [[entry["type"], entry["value"]] for entry in parse_coff_argument_tokens(arg_tokens)])


async def create_coffexec_tasking_response(
    taskData: PTTaskMessageAllData,
    display_command: str = "coffexec",
) -> PTTaskCreateTaskingMessageResponse:
    response = PTTaskCreateTaskingMessageResponse(TaskID=taskData.Task.ID, Success=True)
    group_name = taskData.args.get_parameter_group_name()
    has_new_upload = bool(safe_get_arg(taskData, "bof_file", ""))
    has_registered_name = bool(
        safe_get_arg(taskData, "coff_name", "")
        or safe_get_arg(taskData, "coff", "")
        or safe_get_arg(taskData, "name", "")
    )
    if group_name not in {"Registered", "New"}:
        if has_new_upload:
            group_name = "New"
        elif has_registered_name:
            group_name = "Registered"
    if group_name not in {"Registered", "New"}:
        return PTTaskCreateTaskingMessageResponse(
            TaskID=taskData.Task.ID,
            Success=False,
            Error="coffexec supports only Registered COFF or New BOF tasking",
        )
    if safe_get_arg(taskData, "path") or safe_get_arg(taskData, "coff_b64"):
        return PTTaskCreateTaskingMessageResponse(
            TaskID=taskData.Task.ID,
            Success=False,
            Error="coffexec path and inline COFF tasking are disabled; use Registered or New",
        )

    if safe_get_arg(taskData, "function_name"):
        taskData.args.add_arg("function", safe_get_arg(taskData, "function_name"))
    function = safe_get_arg(taskData, "function", "go") or "go"
    taskData.args.add_arg("function", function)

    typed_args = normalize_typed_args(safe_get_arg(taskData, "coff_arguments", []))
    if typed_args:
        taskData.args.add_arg("typed_args", typed_args)
    try:
        taskData.args.remove_arg("coff_arguments")
    except Exception:
        pass

    if group_name == "New":
        file_id = safe_get_arg(taskData, "bof_file")
        try:
            file_meta = await search_mythic_file(taskData.Task.ID, agent_file_id=file_id)
            file_contents = await fetch_mythic_file_contents(file_id)
        except Exception as exc:
            return PTTaskCreateTaskingMessageResponse(
                TaskID=taskData.Task.ID,
                Success=False,
                Error=f"failed to resolve uploaded COFF: {exc}",
            )
        group_info = [ParameterGroupInfo(required=True, group_name=group_name, ui_position=1)]
        taskData.args.add_arg("coff_name", file_meta.Filename, parameter_group_info=group_info)
        taskData.args.add_arg("coff_b64", base64.b64encode(file_contents).decode("ascii"), parameter_group_info=group_info)
        taskData.args.add_arg("coff_source", "new", parameter_group_info=group_info)
        taskData.args.add_arg("size", len(file_contents), parameter_group_info=group_info)
        taskData.args.add_arg("file_id", file_id, parameter_group_info=group_info)
        taskData.args.remove_arg("bof_file")
        target = file_meta.Filename
    else:
        target = (
            safe_get_arg(taskData, "coff_name", "")
            or safe_get_arg(taskData, "coff", "")
            or safe_get_arg(taskData, "name", "")
            or ""
        )
        if not target:
            return PTTaskCreateTaskingMessageResponse(
                TaskID=taskData.Task.ID,
                Success=False,
                Error="coffexec requires a registered COFF name or New BOF upload",
            )
        try:
            file_meta = await search_mythic_file(taskData.Task.ID, filename=target)
            file_id = getattr(file_meta, "AgentFileId", None) or getattr(file_meta, "AgentFileID", "")
            if not file_id:
                raise ValueError(f"matching Mythic file has no AgentFileId: {target}")
            file_contents = await fetch_mythic_file_contents(file_id)
        except Exception as exc:
            return PTTaskCreateTaskingMessageResponse(
                TaskID=taskData.Task.ID,
                Success=False,
                Error=f"failed to resolve registered COFF {target}: {exc}",
            )
        group_info = [ParameterGroupInfo(required=True, group_name=group_name, ui_position=1)]
        target = file_meta.Filename or target
        taskData.args.add_arg("coff", target, parameter_group_info=group_info)
        taskData.args.add_arg("coff_name", target, parameter_group_info=group_info)
        taskData.args.add_arg("coff_b64", base64.b64encode(file_contents).decode("ascii"), parameter_group_info=group_info)
        taskData.args.add_arg("coff_source", "registered", parameter_group_info=group_info)
        taskData.args.add_arg("size", len(file_contents), parameter_group_info=group_info)
        taskData.args.add_arg("file_id", file_id, parameter_group_info=group_info)

    timeout = safe_get_arg(taskData, "timeout")
    if timeout is None:
        taskData.args.add_arg("timeout", 30)

    response.DisplayParams = (
        f"-Coff {target} -Function {function} "
        f"-Timeout {taskData.args.get_arg('timeout') or 30}"
        f"{typed_args_display(typed_args)}"
    )
    if display_command != "coffexec":
        response.DisplayParams = f"{display_command} {response.DisplayParams}"
    return response


class CoffexecCommand(CommandBase):
    cmd = "coffexec"
    needs_admin = False
    help_cmd = "coffexec -Coff <registered.o> -Function go -Arguments wchar:C:\\\\"
    description = "Execute an x64 COFF/BOF through the native messaging host. Use register_coff first for Apollo-style cached execution."
    version = 2
    author = "@kingofthenops"
    attackmapping = ["T1106"]
    argument_class = CoffexecArguments
    attributes = CommandAttributes(spawn_and_injectable=False, supported_os=[SupportedOS.Windows])

    async def create_go_tasking(self, taskData: PTTaskMessageAllData) -> PTTaskCreateTaskingMessageResponse:
        return await create_coffexec_tasking_response(taskData)

    async def process_response(self, task: PTTaskMessageAllData, response: any) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
