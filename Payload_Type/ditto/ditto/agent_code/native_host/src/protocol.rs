use std::io::{Read, Write};

use crate::crypto::{Envelope, decrypt, encrypt};
use crate::errors::{HostError, Result};

const MAX_MESSAGE: usize = 16 * 1024 * 1024;

#[derive(serde::Deserialize)]
pub struct Request {
    pub id: String,
    pub c: String,
    #[serde(default)]
    pub a: serde_json::Value,
}

#[derive(serde::Serialize)]
pub struct Response {
    pub id: String,
    pub ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub r: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub e: Option<String>,
}

pub enum ReadState {
    Message(Request),
    Eof,
}

pub fn read_request<R: Read>(reader: &mut R) -> Result<ReadState> {
    let mut len_buf = [0u8; 4];
    match reader.read_exact(&mut len_buf) {
        Ok(()) => {}
        Err(error) if error.kind() == std::io::ErrorKind::UnexpectedEof => return Ok(ReadState::Eof),
        Err(error) => return Err(error.into()),
    }
    let len = u32::from_le_bytes(len_buf) as usize;
    if len == 0 || len > MAX_MESSAGE {
        return Err(HostError::BadInput);
    }
    let mut data = vec![0u8; len];
    reader.read_exact(&mut data)?;
    let envelope: Envelope = serde_json::from_slice(&data)?;
    let plain = decrypt(&envelope)?;
    let request: Request = serde_json::from_slice(&plain)?;
    Ok(ReadState::Message(request))
}

pub fn write_response<W: Write>(writer: &mut W, response: &Response) -> Result<()> {
    let plain = serde_json::to_vec(response)?;
    let envelope = encrypt(&plain)?;
    let data = serde_json::to_vec(&envelope)?;
    if data.len() > MAX_MESSAGE {
        return Err(HostError::BadInput);
    }
    writer.write_all(&(data.len() as u32).to_le_bytes())?;
    writer.write_all(&data)?;
    writer.flush()?;
    Ok(())
}
