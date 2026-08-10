<p align="center">
  <img alt="C2 Logo" src="agent_icons/ditto-group.png" height="30%" width="30%">
</p>

# Ditto

Ditto is a Mythic payload type that builds a Chromium extension as the agent artifact. Ditto is based on the [chromealone](https://github.com/praetorian-inc/chromealone) project

The built extension checks in to Mythic over HTTP(S) and currently supports browser-scoped tasking such as tab enumeration, cookie collection, screenshots, history search, DNS lookup, exit, and runtime sleep changes. The extension's capabilities can include SOCKS if the IWA option is included, and if native messenger app is included, the extension can interact with the OS with coffexec.

## Installation

```
mythic-cli install folder /path/to/ditto
```

## Notable Features

- Builds a zipped Chromium extension payload for Mythic.
- Optionally builds a signed Isolated Web App.
- Optionally builds a native messaging host.
- Supports optional extension JavaScript obfuscation in the builder.

## Native Messaging Host Build Option

Set `build_native_host=true` to compile and package the Rust native messaging
host in the Mythic build pipeline.
The extension is packaged with the
`nativeMessaging` permission, an encrypted native-host IPC key, the host EXE,
and a Chrome native messaging manifest.
Ditto uses `chrome.runtime.connectNative()`

Configurable native host build parameters:

- `native_host_allowed_extension_id`: optional Chrome extension ID for `allowed_origins`; if blank, the builder derives it from `manifest_key` when possible
- `native_host_company`: Version resource CompanyName
- `native_host_description`: Version resource FileDescription
- `native_host_exe_name`: EXE filename packaged under `native_host/`
- `native_host_name`: host name written into the generated JSON, for example `com.microsoft.device_health`
- `native_host_product`: Version resource ProductName and signing product label
- `native_host_sign`: self-sign the EXE in the build container
- `native_host_signer_subject`: self-signed certificate common name

Native host capabilities are selected in Mythic's Select Commands phase. The
builder derives the Rust feature list from selected commands, so deselected
commands are not compiled into the native host EXE. Select one or more of:
`ls`, `ps`, `upload`, `download`, `coffexec`, and `launch_iwa_hidden_desktop`.
Select `register_coff` alongside `coffexec` to run a BOF

Build guardrails:

- Selecting any native-host-backed command requires `build_native_host=true`.
- Setting `build_native_host=true` requires at least one native-host-backed command to be selected.
- `register_coff` also requires `build_native_host=true`; it caches encrypted BOF bytes in extension storage for later native-host execution.

Native host artifacts are included inside the extension package:

```text
manifest.json
service_worker.js
config.js
<native_host_name>.json
native_host/<native_host_exe_name>
native_host/README.txt
```

The generated JSON uses a path relative to the unpacked extension folder:

```json
{
  "name": "com.microsoft.device_health",
  "path": "native_host\\DeviceHealthHost.exe",
  "type": "stdio",
  "allowed_origins": ["chrome-extension://<extension-id>/"]
}
```

Register it by pointing Chrome at the JSON file:

```text
reg add HKCU\Software\Google\Chrome\NativeMessagingHosts\<native_host_name> /ve /t REG_SZ /d "<absolute path to extension\<native_host_name>.json>" /f
```

## IWA Build Option

Set `build_iwa=true` in the payload build parameters to emit a combined zip:

```text
extension/
extension.zip
iwa/app.swbn
iwa/install-artifacts/webapp.pb
iwa/install-artifacts/iwa-key-distribution.pb
iwa/install-artifacts/install-info.json
iwa/install-artifacts/bundle-info.json
iwa/README.txt
```

The IWA build is fully handled in the Mythic build pipeline. The builder signs the web bundle, extracts the current integrity-block signature, calculates the Chrome app ID from the current `isolated-app://` origin, and patches the Chrome `WebApp` protobuf template so SilentChrome can seed the profile without using `chrome://web-app-internals/`.
The builder also emits a minimal `iwa-key-distribution.pb` with a
`user_install_allowlist` entry for the generated signed Web Bundle ID. That
entry grants `DIRECT_SOCKETS` and `DIRECT_SOCKETS_PRIVATE` for versions starting
at `0.0.0`. SilentChrome can either generate the same file on-target from
`webapp.pb`, or register the prebuilt file from the payload package. In both
cases SilentChrome also creates the required sibling
`IwaKeyDistribution\<version>\manifest.json` component manifest.

Configurable IWA build parameters:

- `iwa_private_key_b64`: optional base64-encoded PEM bytes for
  `private-ecdsa-p256.key`; if blank, the build generates a fresh P-256 key
- `iwa_bridge_extension_id`
- `iwa_control_host` / `iwa_control_port`
- `iwa_debug_local_socks`
- `iwa_auto_start_socks`
- `iwa_socks_host` / `iwa_socks_port`

If `iwa_bridge_extension_id` is blank and `manifest_key` is supplied, the builder derives the deterministic extension ID from the manifest key and embeds it into the IWA config.
Use the generated `iwa/install-artifacts/install-info.json` as the source of truth for the IWA `app_id` and `web_bundle_id`; both can change when the IWA signing key changes. To keep them stable across builds, pass the same `iwa_private_key_b64` value. `launch_iwa_hidden_desktop` accepts the Chrome app ID directly, or an `isolated-app://...` URL/web bundle ID and normalizes it before tasking the native host.

Normal IWA builds keep only the control WebSocket. The Mythic SOCKS bridge sends SOCKS frames extension -> IWA over that WebSocket, then the IWA opens outbound Direct Sockets to targets. `iwa_debug_local_socks=true` is only for local testing with tools such as `curl -x socks5://127.0.0.1:38900`; when it is false, no local SOCKS listener is configured or auto-started.

IWA-backed tasking is also selected in Mythic's Select Commands phase. Selecting
`launch_iwa_extension`, `close_iwa_extension`, `iwa_status`, `iwa_ping`,
`iwa_control`, `iwa_start_socks`, `iwa_stop_socks`, `socks`, or
`launch_iwa_hidden_desktop` requires `build_iwa=true`; otherwise
the builder fails instead of producing a payload with unusable tasking.

The checked-in IWA source keeps `package-lock.json`, `public/.well-known/manifest.webmanifest`, `install-artifacts/install-info.template.json`, and `install-artifacts/public-manual-webapp.pb`. The protobuf template must include the stored WebApp `permissions_policy` entries for `cross-origin-isolated`, `direct-sockets`, `direct-sockets-private`, and local-network access; otherwise Chrome can launch the IWA but `TCPServerSocket` fails with a Permissions-Policy `NotAllowedError`. Local npm dependencies, generated signing keys, `dist-wbn/`, `app.swbn`, and patched install metadata are build outputs.

SilentChrome should install the generated IWA with Direct Sockets entitlements and profile-local local-network permissions. The preferred two-file flow stages only `app.swbn` and `webapp.pb`; SilentChrome derives the signed Web Bundle ID from `webapp.pb` and creates a high-version local `IwaKeyDistribution` component on-target

Upload or stage `iwa/app.swbn` and `iwa/install-artifacts/webapp.pb` to the host
first. The generated `iwa/README.txt` contains concrete 
commands to install the IWA using SilentChrome-BOF. Use `--iwa-register-key-distribution` only when staging Ditto's
prebuilt `iwa-key-distribution.pb`; use `--iwa-entitle-direct-sockets` only when
patching an existing Chrome-provided key-distribution PB. SilentChrome always
seeds the Chrome profile `Preferences` content-setting exceptions for
`local_network`, `loopback_network`, and `local_network_access`. The manifest
and key distribution alone are not enough for private or loopback Direct Sockets
targets.

There is no need to enable `enable-isolated-web-app-dev-mode@1` for the normal install path.
The production-style path uses only `enable-isolated-web-apps@1` plus the local
key-distribution component. Chrome 148 testing showed that a generated
`iwa-key-distribution.pb` without the sibling `manifest.json` is ignored and
replaced by Chrome's official component; with the manifest present, Direct
Sockets starts without the dev-mode banner.

## Commands

Current command set:

- `ping`
- `list_tabs`
- `get_cookies`
- `capture_tab`
- `history_search`
- `dns_lookup`
- `ls`
- `ps`
- `upload`
- `download`
- `register_coff`
- `coffexec`
- `launch_iwa_hidden_desktop`
- `launch_iwa_extension`
- `close_iwa_extension`
- `iwa_status`
- `iwa_ping`
- `iwa_control`
- `iwa_start_socks`
- `iwa_stop_socks`
- `socks`
- `sleep`
- `exit`
