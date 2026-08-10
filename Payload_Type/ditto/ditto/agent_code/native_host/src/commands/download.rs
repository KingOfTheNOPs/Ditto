use std::io::{Read, Seek, SeekFrom};

use base64::Engine;
use base64::engine::general_purpose::STANDARD;
use serde_json::json;

use crate::commands::{optional_u64, value_string};
use crate::errors::Result;

pub const NAME: &str = "download";
const MAX_READ: u64 = 768 * 1024;

pub fn run(args: &serde_json::Value) -> Result<serde_json::Value> {
    let path = value_string(args, "path")?;
    let offset = optional_u64(args, "offset", 0);
    let length = optional_u64(args, "length", 256 * 1024).min(MAX_READ);

    let mut file = std::fs::File::open(path)?;
    let file_len = file.metadata()?.len();
    file.seek(SeekFrom::Start(offset))?;

    let mut buffer = vec![0u8; length as usize];
    let read = file.read(&mut buffer)?;
    buffer.truncate(read);

    Ok(json!({
        "path": path,
        "offset": offset,
        "read": read,
        "file_len": file_len,
        "eof": offset + read as u64 >= file_len,
        "data_b64": STANDARD.encode(&buffer),
    }))
}
