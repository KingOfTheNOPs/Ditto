use aes_gcm::aead::{Aead, KeyInit};
use aes_gcm::{Aes256Gcm, Nonce};
use base64::Engine;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use zeroize::Zeroize;

use crate::errors::{HostError, Result};

include!(concat!(env!("OUT_DIR"), "/key_blob.rs"));

const KID: &str = "a1";

#[derive(serde::Deserialize, serde::Serialize)]
pub struct Envelope {
    pub v: u8,
    pub k: String,
    pub n: String,
    pub d: String,
}

fn key_bytes() -> [u8; 32] {
    let mut key = [0u8; 32];
    for idx in 0..32 {
        key[idx] = KEY_MASK[idx] ^ KEY_XOR[idx];
    }
    key
}

pub fn decrypt(envelope: &Envelope) -> Result<Vec<u8>> {
    if envelope.v != 1 {
        return Err(HostError::BadInput);
    }
    let mut key = key_bytes();
    let cipher = Aes256Gcm::new_from_slice(&key).map_err(|_| HostError::Crypto)?;
    let nonce = URL_SAFE_NO_PAD.decode(&envelope.n)?;
    if nonce.len() != 12 {
        key.zeroize();
        return Err(HostError::Crypto);
    }
    let data = URL_SAFE_NO_PAD.decode(&envelope.d)?;
    let plain = cipher
        .decrypt(Nonce::from_slice(&nonce), data.as_ref())
        .map_err(|_| HostError::Crypto)?;
    key.zeroize();
    Ok(plain)
}

pub fn encrypt(plain: &[u8]) -> Result<Envelope> {
    let mut key = key_bytes();
    let cipher = Aes256Gcm::new_from_slice(&key).map_err(|_| HostError::Crypto)?;
    let mut nonce = [0u8; 12];
    getrandom::fill(&mut nonce).map_err(|_| HostError::Crypto)?;
    let encrypted = cipher
        .encrypt(Nonce::from_slice(&nonce), plain)
        .map_err(|_| HostError::Crypto)?;
    key.zeroize();
    Ok(Envelope {
        v: 1,
        k: KID.to_string(),
        n: URL_SAFE_NO_PAD.encode(nonce),
        d: URL_SAFE_NO_PAD.encode(encrypted),
    })
}
