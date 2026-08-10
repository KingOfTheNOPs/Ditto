use std::time::UNIX_EPOCH;

use serde_json::json;

use crate::commands::optional_string;
use crate::errors::Result;

pub const NAME: &str = "ls";

pub fn run(args: &serde_json::Value) -> Result<serde_json::Value> {
    let path = optional_string(args, "path").unwrap_or(".");
    let mut entries = Vec::new();

    for item in std::fs::read_dir(path)? {
        let item = item?;
        let metadata = item.metadata()?;
        let modified = metadata
            .modified()
            .ok()
            .and_then(|time| time.duration_since(UNIX_EPOCH).ok())
            .map(|duration| duration.as_secs());
        entries.push(json!({
            "name": item.file_name().to_string_lossy(),
            "path": item.path().to_string_lossy(),
            "dir": metadata.is_dir(),
            "len": metadata.len(),
            "mtime": modified,
        }));
    }

    Ok(json!({
        "path": path,
        "entries": entries,
    }))
}
