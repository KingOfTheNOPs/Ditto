#[cfg(feature = "debug_log")]
pub fn log_line(message: &str) {
    use std::io::Write;
    let path = std::env::temp_dir().join("devicehealthhost.log");
    if let Ok(mut file) = std::fs::OpenOptions::new().create(true).append(true).open(path) {
        let _ = writeln!(file, "{}", message);
    }
}

#[cfg(not(feature = "debug_log"))]
pub fn log_line(_message: &str) {}
