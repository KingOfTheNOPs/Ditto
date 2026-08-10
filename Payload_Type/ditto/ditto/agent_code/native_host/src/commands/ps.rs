use serde_json::json;
use windows_sys::Win32::Foundation::{CloseHandle, INVALID_HANDLE_VALUE};
use windows_sys::Win32::System::Diagnostics::ToolHelp::{
    CreateToolhelp32Snapshot, PROCESSENTRY32W, Process32FirstW, Process32NextW, TH32CS_SNAPPROCESS,
};

use crate::errors::{HostError, Result};

pub const NAME: &str = "ps";

fn wide_name(buf: &[u16]) -> String {
    let end = buf.iter().position(|c| *c == 0).unwrap_or(buf.len());
    String::from_utf16_lossy(&buf[..end])
}

pub fn run(_args: &serde_json::Value) -> Result<serde_json::Value> {
    let snapshot = unsafe { CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0) };
    if snapshot == INVALID_HANDLE_VALUE {
        return Err(HostError::Windows(unsafe { windows_sys::Win32::Foundation::GetLastError() }));
    }

    let mut entry = PROCESSENTRY32W {
        dwSize: std::mem::size_of::<PROCESSENTRY32W>() as u32,
        ..unsafe { std::mem::zeroed() }
    };
    let mut rows = Vec::new();
    let mut ok = unsafe { Process32FirstW(snapshot, &mut entry) } != 0;
    while ok {
        rows.push(json!({
            "pid": entry.th32ProcessID,
            "ppid": entry.th32ParentProcessID,
            "threads": entry.cntThreads,
            "exe": wide_name(&entry.szExeFile),
        }));
        ok = unsafe { Process32NextW(snapshot, &mut entry) } != 0;
    }
    unsafe {
        CloseHandle(snapshot);
    }

    Ok(json!({
        "processes": rows,
    }))
}
