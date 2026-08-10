use std::io::Write;

use base64::Engine;
use base64::engine::general_purpose::STANDARD;
use serde_json::json;

use crate::commands::{optional_bool, optional_string, value_string};
use crate::errors::Result;

pub const NAME: &str = "upload";

pub fn run(args: &serde_json::Value) -> Result<serde_json::Value> {
    let path = value_string(args, "path")?;
    let data = optional_string(args, "data_b64")
        .or_else(|| optional_string(args, "data"))
        .ok_or(crate::errors::HostError::BadInput)?;
    let bytes = STANDARD.decode(data)?;

    if optional_bool(args, "create_dirs", true) {
        if let Some(parent) = std::path::Path::new(path).parent() {
            if !parent.as_os_str().is_empty() {
                std::fs::create_dir_all(parent)?;
            }
        }
    }

    let mut options = std::fs::OpenOptions::new();
    options.create(true).write(true);
    if optional_bool(args, "append", false) {
        options.append(true);
    } else {
        options.truncate(true);
    }
    let mut file = options.open(path)?;
    file.write_all(&bytes)?;

    Ok(json!({
        "path": path,
        "written": bytes.len(),
    }))
}
