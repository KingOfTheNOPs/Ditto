mod commands;
mod crypto;
mod debug;
mod errors;
mod protocol;

use std::io::{BufReader, BufWriter};

use protocol::{ReadState, Response};

fn main() {
    if run().is_err() {
        debug::log_line("exit");
    }
}

fn run() -> errors::Result<()> {
    let stdin = std::io::stdin();
    let stdout = std::io::stdout();
    let mut reader = BufReader::new(stdin.lock());
    let mut writer = BufWriter::new(stdout.lock());

    loop {
        let request = match protocol::read_request(&mut reader)? {
            ReadState::Message(request) => request,
            ReadState::Eof => break,
        };
        let id = request.id.clone();
        let response = match commands::dispatch(&request) {
            Ok(value) => Response {
                id,
                ok: true,
                r: Some(value),
                e: None,
            },
            Err(error) => Response {
                id,
                ok: false,
                r: None,
                e: Some(error.to_string()),
            },
        };
        protocol::write_response(&mut writer, &response)?;
    }
    Ok(())
}
