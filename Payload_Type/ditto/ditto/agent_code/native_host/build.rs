use std::env;
use std::fs;
use std::path::PathBuf;
use std::process::Command;

use base64::Engine;
use base64::engine::general_purpose::{STANDARD, URL_SAFE_NO_PAD};

fn decode_key(value: &str) -> Vec<u8> {
    STANDARD
        .decode(value)
        .or_else(|_| URL_SAFE_NO_PAD.decode(value))
        .expect("NM_PSK_B64 must be valid base64")
}

fn rc_escape(value: &str) -> String {
    value.replace('\\', "\\\\").replace('"', "\\\"")
}

fn tool_default(windows_name: &str, linux_name: &str) -> String {
    if cfg!(windows) {
        format!(r"C:\ProgramData\mingw64\mingw64\bin\{windows_name}.exe")
    } else {
        linux_name.to_string()
    }
}

fn main() {
    println!("cargo:rerun-if-env-changed=NM_PSK_B64");
    println!("cargo:rerun-if-env-changed=NM_COMPANY");
    println!("cargo:rerun-if-env-changed=NM_PRODUCT");
    println!("cargo:rerun-if-env-changed=NM_DESCRIPTION");
    println!("cargo:rerun-if-env-changed=NM_ORIGINAL_FILENAME");

    let out_dir = PathBuf::from(env::var("OUT_DIR").expect("OUT_DIR missing"));
    let key_b64 = env::var("NM_PSK_B64").unwrap_or_else(|_| {
        "c7+Vhc2xfM+SOXHFrg9thzVKJKgLsQaF+TyoyH7cNdA=".to_string()
    });
    let key = decode_key(&key_b64);
    assert_eq!(key.len(), 32, "NM_PSK_B64 must decode to 32 bytes");

    let mut mask = [0u8; 32];
    getrandom::fill(&mut mask).expect("getrandom failed");
    let mut xored = [0u8; 32];
    for (idx, byte) in key.iter().enumerate() {
        xored[idx] = *byte ^ mask[idx];
    }

    let key_rs = format!(
        "pub const KEY_MASK: [u8; 32] = {:?};\npub const KEY_XOR: [u8; 32] = {:?};\n",
        mask, xored
    );
    fs::write(out_dir.join("key_blob.rs"), key_rs).expect("failed to write key blob");

    let company = env::var("NM_COMPANY").unwrap_or_else(|_| "Browser Components".to_string());
    let product = env::var("NM_PRODUCT").unwrap_or_else(|_| "Browser Support Host".to_string());
    let description = env::var("NM_DESCRIPTION").unwrap_or_else(|_| "Browser Support Host".to_string());
    let original =
        env::var("NM_ORIGINAL_FILENAME").unwrap_or_else(|_| "BrowserSupportHost.exe".to_string());

    let rc = format!(
        r#"#include <windows.h>
1 VERSIONINFO
FILEVERSION 10,0,19041,1
PRODUCTVERSION 10,0,19041,1
FILEFLAGSMASK 0x3fL
FILEFLAGS 0
FILEOS 0x40004L
FILETYPE 0x1L
FILESUBTYPE 0
BEGIN
  BLOCK "StringFileInfo"
  BEGIN
    BLOCK "040904B0"
    BEGIN
      VALUE "CompanyName", "{company}\0"
      VALUE "FileDescription", "{description}\0"
      VALUE "FileVersion", "10.0.19041.1\0"
      VALUE "InternalName", "{original}\0"
      VALUE "OriginalFilename", "{original}\0"
      VALUE "ProductName", "{product}\0"
      VALUE "ProductVersion", "10.0.19041.1\0"
    END
  END
  BLOCK "VarFileInfo"
  BEGIN
    VALUE "Translation", 0x0409, 1200
  END
END
"#,
        company = rc_escape(&company),
        description = rc_escape(&description),
        original = rc_escape(&original),
        product = rc_escape(&product),
    );
    let rc_path = out_dir.join("version.rc");
    let res_path = out_dir.join("version.res");
    fs::write(&rc_path, rc).expect("failed to write version rc");
    let windres = env::var("WINDRES")
        .unwrap_or_else(|_| tool_default("windres", "x86_64-w64-mingw32-windres"));
    let status = Command::new(windres)
        .arg(&rc_path)
        .arg("-O")
        .arg("coff")
        .arg("-o")
        .arg(&res_path)
        .status()
        .expect("failed to run windres");
    if status.success() {
        println!("cargo:rustc-link-arg={}", res_path.display());
    }

}
