use serde_json::json;
use windows_sys::Win32::Foundation::{CloseHandle, GetLastError};
use windows_sys::Win32::System::StationsAndDesktops::{
    CloseDesktop, CreateDesktopW, OpenDesktopW,
};
use windows_sys::Win32::System::Threading::{
    CREATE_NEW_CONSOLE, CreateProcessW, NORMAL_PRIORITY_CLASS, PROCESS_INFORMATION,
    STARTF_USESHOWWINDOW, STARTUPINFOW,
};
use windows_sys::Win32::UI::WindowsAndMessaging::{SW_HIDE, SW_SHOWNORMAL};

use crate::commands::{optional_bool, optional_string, optional_u64, value_string};
use crate::errors::{HostError, Result};

pub const NAME: &str = "launch_iwa_hidden_desktop";

const DESKTOP_READOBJECTS: u32 = 0x0001;
const DESKTOP_CREATEWINDOW: u32 = 0x0002;
const DESKTOP_CREATEMENU: u32 = 0x0004;
const DESKTOP_HOOKCONTROL: u32 = 0x0008;
const DESKTOP_JOURNALRECORD: u32 = 0x0010;
const DESKTOP_JOURNALPLAYBACK: u32 = 0x0020;
const DESKTOP_ENUMERATE: u32 = 0x0040;
const DESKTOP_WRITEOBJECTS: u32 = 0x0080;
const DESKTOP_SWITCHDESKTOP: u32 = 0x0100;
const GENERIC_ALL: u32 = 0x10000000;
const STANDARD_RIGHTS_REQUIRED: u32 = 0x000F0000;
const DESKTOP_ACCESS: u32 = DESKTOP_READOBJECTS
    | DESKTOP_CREATEWINDOW
    | DESKTOP_CREATEMENU
    | DESKTOP_HOOKCONTROL
    | DESKTOP_JOURNALRECORD
    | DESKTOP_JOURNALPLAYBACK
    | DESKTOP_ENUMERATE
    | DESKTOP_WRITEOBJECTS
    | DESKTOP_SWITCHDESKTOP
    | GENERIC_ALL
    | STANDARD_RIGHTS_REQUIRED;

fn wide(value: &str) -> Vec<u16> {
    value.encode_utf16().chain(std::iter::once(0)).collect()
}

fn quote(value: &str) -> String {
    if value.starts_with('"') || !value.chars().any(|c| c == ' ' || c == '\t') {
        value.to_string()
    } else {
        format!("\"{}\"", value)
    }
}

fn chrome_path() -> &'static str {
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
}

fn optional_nonempty_string<'a>(args: &'a serde_json::Value, name: &str) -> Option<&'a str> {
    optional_string(args, name).and_then(|value| {
        let trimmed = value.trim();
        if trimmed.is_empty() {
            None
        } else {
            Some(trimmed)
        }
    })
}

fn desktop_object_name(desktop: &str) -> &str {
    desktop
        .rsplit(['\\', '/'])
        .next()
        .filter(|value| !value.trim().is_empty())
        .unwrap_or(desktop)
}

fn valid_chrome_app_id(value: &str) -> bool {
    value.len() == 32 && value.bytes().all(|byte| (b'a'..=b'p').contains(&byte))
}

pub fn run(args: &serde_json::Value) -> Result<serde_json::Value> {
    let app_id = value_string(args, "app_id")?;
    if !valid_chrome_app_id(app_id) {
        return Err(HostError::BadInput);
    }
    let path = optional_string(args, "path").unwrap_or(chrome_path());
    let desktop = optional_nonempty_string(args, "desktop").unwrap_or("WinSta0\\DeviceHealth");
    let create_desktop_name = desktop_object_name(desktop);
    let show = optional_bool(args, "show", false);
    let new_console = optional_bool(args, "new_console", false);
    let hold_ms = optional_u64(args, "hold_ms", 0);

    let mut chrome_args = vec![format!("--app-id={}", app_id)];
    if let Some(user_data_dir) = optional_nonempty_string(args, "user_data_dir") {
        chrome_args.push(format!("--user-data-dir={}", quote(user_data_dir)));
    }
    if let Some(profile) = optional_nonempty_string(args, "profile") {
        chrome_args.push(format!("--profile-directory={}", quote(profile)));
    }
    if let Some(extra) = optional_nonempty_string(args, "extra_args") {
        chrome_args.push(extra.to_string());
    }
    let command_line = format!("{} {}", quote(path), chrome_args.join(" "));

    let create_desktop_w = wide(create_desktop_name);
    let hdesk = unsafe {
        let created = CreateDesktopW(
            create_desktop_w.as_ptr(),
            std::ptr::null(),
            std::ptr::null_mut(),
            0,
            DESKTOP_ACCESS,
            std::ptr::null(),
        );
        if !created.is_null() {
            created
        } else {
            OpenDesktopW(create_desktop_w.as_ptr(), 0, 0, DESKTOP_ACCESS)
        }
    };
    if hdesk.is_null() {
        return Err(HostError::Windows(unsafe { GetLastError() }));
    }

    let path_w = wide(path);
    let startup_desktop_w = wide(desktop);
    let mut cmd_w = wide(&command_line);
    let mut si = STARTUPINFOW {
        cb: std::mem::size_of::<STARTUPINFOW>() as u32,
        lpDesktop: startup_desktop_w.as_ptr() as *mut u16,
        dwFlags: STARTF_USESHOWWINDOW,
        wShowWindow: if show { SW_SHOWNORMAL as u16 } else { SW_HIDE as u16 },
        ..unsafe { std::mem::zeroed() }
    };
    let mut pi: PROCESS_INFORMATION = unsafe { std::mem::zeroed() };
    let mut flags = NORMAL_PRIORITY_CLASS;
    if new_console {
        flags |= CREATE_NEW_CONSOLE;
    }
    let ok = unsafe {
        CreateProcessW(
            path_w.as_ptr(),
            cmd_w.as_mut_ptr(),
            std::ptr::null(),
            std::ptr::null(),
            0,
            flags,
            std::ptr::null(),
            std::ptr::null(),
            &mut si,
            &mut pi,
        )
    };
    let last_error = unsafe { GetLastError() };
    unsafe {
        CloseDesktop(hdesk);
    }
    if ok == 0 {
        return Err(HostError::Windows(last_error));
    }
    if hold_ms > 0 {
        std::thread::sleep(std::time::Duration::from_millis(hold_ms));
    }
    unsafe {
        CloseHandle(pi.hThread);
        CloseHandle(pi.hProcess);
    }

    Ok(json!({
        "pid": pi.dwProcessId,
        "tid": pi.dwThreadId,
        "desktop": desktop,
        "desktop_object": create_desktop_name,
        "path": path,
    }))
}
