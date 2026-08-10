use thiserror::Error;

#[derive(Debug, Error)]
pub enum HostError {
    #[error("bad input")]
    BadInput,
    #[error("unsupported")]
    Unsupported,
    #[error("crypto")]
    Crypto,
    #[error("io")]
    Io(#[from] std::io::Error),
    #[error("json")]
    Json(#[from] serde_json::Error),
    #[error("base64")]
    Base64(#[from] base64::DecodeError),
    #[error("windows:{0}")]
    Windows(u32),
    #[error("coff:{0}")]
    CoffText(String),
}

pub type Result<T> = std::result::Result<T, HostError>;
