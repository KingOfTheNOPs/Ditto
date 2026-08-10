use crate::errors::{HostError, Result};
use crate::protocol::Request;

#[cfg(feature = "cmd_ls")]
mod ls;
#[cfg(feature = "cmd_ps")]
mod ps;
#[cfg(feature = "cmd_upload")]
mod upload;
#[cfg(feature = "cmd_download")]
mod download;
#[cfg(feature = "cmd_coffexec")]
mod coffexec;
#[cfg(feature = "cmd_iwa")]
mod iwa;

pub fn dispatch(request: &Request) -> Result<serde_json::Value> {
    #[cfg(feature = "cmd_ls")]
    if request.c == ls::NAME {
        return ls::run(&request.a);
    }

    #[cfg(feature = "cmd_ps")]
    if request.c == ps::NAME {
        return ps::run(&request.a);
    }

    #[cfg(feature = "cmd_upload")]
    if request.c == upload::NAME {
        return upload::run(&request.a);
    }

    #[cfg(feature = "cmd_download")]
    if request.c == download::NAME {
        return download::run(&request.a);
    }

    #[cfg(feature = "cmd_coffexec")]
    if request.c == coffexec::NAME {
        return coffexec::run(&request.a);
    }

    #[cfg(feature = "cmd_iwa")]
    if request.c == iwa::NAME {
        return iwa::run(&request.a);
    }

    Err(HostError::Unsupported)
}

fn value_string<'a>(args: &'a serde_json::Value, name: &str) -> Result<&'a str> {
    args.get(name)
        .and_then(|v| v.as_str())
        .ok_or(HostError::BadInput)
}

fn optional_string<'a>(args: &'a serde_json::Value, name: &str) -> Option<&'a str> {
    args.get(name).and_then(|v| v.as_str())
}

fn optional_u64(args: &serde_json::Value, name: &str, default: u64) -> u64 {
    args.get(name).and_then(|v| v.as_u64()).unwrap_or(default)
}

fn optional_bool(args: &serde_json::Value, name: &str, default: bool) -> bool {
    args.get(name).and_then(|v| v.as_bool()).unwrap_or(default)
}
