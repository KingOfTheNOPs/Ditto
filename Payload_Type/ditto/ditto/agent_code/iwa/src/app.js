import { CONFIG } from "./config.js";
import { WebSocketServer } from "./websocket-server.js";
import { SocksServer } from "./socks-server.js";
import { MythicSocksRelay } from "./mythic-socks-relay.js";
import { decodeText, encodeText } from "./codec.js";

const logEl = document.getElementById("log");
const healthEl = document.getElementById("health");
const summaryEl = document.getElementById("summary");
const controlStatusEl = document.getElementById("controlStatus");
const socksStatusEl = document.getElementById("socksStatus");
const extensionStatusEl = document.getElementById("extensionStatus");
const controlPortEl = document.getElementById("controlPort");
const socksPortEl = document.getElementById("socksPort");
const clientCountEl = document.getElementById("clientCount");

document.body.classList.toggle("debug-ui", Boolean(CONFIG.debugUi));
document.title = CONFIG.debugUi ? "Ditto IWA" : "Google Chrome";

if (!CONFIG.debugUi) {
  window.addEventListener("beforeunload", (event) => {
    event.preventDefault();
    event.returnValue = "";
  });
}

const state = {
  startedAt: new Date().toISOString(),
  extensionId: CONFIG.bridgeExtensionId,
  extensionHandshake: null,
  lastError: "",
  control: null,
  socks: null,
  mythicRelay: null
};

function log(message, ...args) {
  const line = `[${new Date().toISOString()}] ${message}${args.length ? ` ${args.map((arg) => JSON.stringify(arg)).join(" ")}` : ""}`;
  console.log(line);
  logEl.textContent = `${line}\n${logEl.textContent}`.slice(0, 24000);
  updateUi();
}

function getLogText(limit = 12000) {
  return logEl.textContent.slice(0, Math.max(0, Number(limit) || 12000));
}

function setHealth(value, klass = "") {
  healthEl.textContent = value;
  healthEl.className = `health ${klass}`.trim();
}

function withTimeout(promise, timeoutMs, label, onTimeout) {
  let timer = null;
  return new Promise((resolve, reject) => {
    timer = setTimeout(async () => {
      try {
        if (onTimeout) {
          await onTimeout();
        }
      } catch (_) {
      }
      reject(new Error(`${label} timed out after ${timeoutMs}ms`));
    }, timeoutMs);

    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        clearTimeout(timer);
        reject(error);
      }
    );
  });
}

async function tcpProbe(request) {
  const host = String(request.host || request.address || "").trim();
  const port = Number(request.port);
  const timeoutMs = Math.max(1000, Number(request.timeout_ms || request.timeoutMs || 8000));
  const requestText = request.request || request.write || "";
  const shouldRead = Boolean(request.read || requestText);

  if (!host || !Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error("tcp_probe requires host and numeric port");
  }
  if (!("TCPSocket" in globalThis)) {
    throw new Error("Direct Sockets TCPSocket is not available");
  }

  const started = performance.now();
  const socket = new TCPSocket(host, port);
  let reader = null;
  let writer = null;

  try {
    const open = await withTimeout(
      socket.opened,
      timeoutMs,
      `tcp_probe open ${host}:${port}`,
      async () => {
        try {
          await socket.close();
        } catch (_) {
        }
      }
    );
    const result = {
      ok: true,
      host,
      port,
      openedMs: Math.round(performance.now() - started),
      localAddress: open.localAddress || "",
      localPort: open.localPort || 0,
      remoteAddress: open.remoteAddress || "",
      remotePort: open.remotePort || 0
    };

    if (requestText) {
      writer = open.writable.getWriter();
      await withTimeout(
        writer.write(encodeText(String(requestText))),
        timeoutMs,
        `tcp_probe write ${host}:${port}`,
        async () => socket.close()
      );
      result.wroteBytes = encodeText(String(requestText)).length;
      writer.releaseLock();
      writer = null;
    }

    if (shouldRead) {
      reader = open.readable.getReader();
      const read = await withTimeout(
        reader.read(),
        timeoutMs,
        `tcp_probe read ${host}:${port}`,
        async () => socket.close()
      );
      const value = read.value instanceof Uint8Array ? read.value : new Uint8Array(0);
      result.read = {
        done: Boolean(read.done),
        bytes: value.length,
        text: decodeText(value.slice(0, 512))
      };
      reader.releaseLock();
      reader = null;
    }

    return result;
  } finally {
    try {
      if (reader) {
        reader.releaseLock();
      }
    } catch (_) {
    }
    try {
      if (writer) {
        writer.releaseLock();
      }
    } catch (_) {
    }
    try {
      await socket.close();
    } catch (_) {
    }
  }
}

function controlStatus() {
  return state.control ? state.control.getStatus() : {
    running: false,
    host: CONFIG.controlHost,
    port: CONFIG.controlPort,
    clients: 0
  };
}

function socksStatus() {
  return state.socks ? state.socks.getStatus() : {
    enabled: Boolean(CONFIG.localSocksEnabled),
    running: false,
    host: CONFIG.socksHost,
    port: CONFIG.socksPort,
    clients: 0
  };
}

function getStatus() {
  const control = controlStatus();
  const socks = socksStatus();
  return {
    ok: true,
    app: "ditto-iwa",
    version: "0.1.0",
    startedAt: state.startedAt,
    href: location.href,
    origin: location.origin,
    directSockets: {
      TCPServerSocket: "TCPServerSocket" in globalThis,
      TCPSocket: "TCPSocket" in globalThis
    },
    extension: {
      configuredId: state.extensionId,
      handshake: state.extensionHandshake
    },
    control,
    socks,
    mythicSocks: state.mythicRelay ? state.mythicRelay.getStatus() : {
      running: false,
      connections: 0
    },
    lastError: state.lastError
  };
}

function updateUi() {
  const status = getStatus();
  controlStatusEl.textContent = status.control.running ? "listening" : "stopped";
  socksStatusEl.textContent = !CONFIG.localSocksEnabled ? "disabled" : (status.socks.running ? "listening" : "stopped");
  extensionStatusEl.textContent = status.extension.handshake ? "connected" : (status.extension.configuredId ? "configured" : "not configured");
  controlPortEl.textContent = String(status.control.port);
  socksPortEl.textContent = CONFIG.localSocksEnabled ? String(status.socks.port) : "websocket";
  clientCountEl.textContent = String(status.control.clients + status.socks.clients);
  summaryEl.textContent = status.lastError || `${status.control.host}:${status.control.port} control, local SOCKS ${CONFIG.localSocksEnabled ? status.socks.host + ":" + status.socks.port : "disabled"}`;

  if (status.control.running && (!CONFIG.localSocksEnabled || status.socks.running)) {
    setHealth("ready", "ok");
  } else if (status.control.running) {
    setHealth("control", "warn");
  } else {
    setHealth("starting", "");
  }
}

async function startControl() {
  if (state.control) {
    return state.control.getStatus();
  }
  state.control = new WebSocketServer({
    host: CONFIG.controlHost,
    port: CONFIG.controlPort,
    log,
    onMessage: handleControlMessage
  });
  state.mythicRelay = new MythicSocksRelay({
    log,
    emit: async (connection, message) => {
      if (!state.control || !connection || !state.control.connections.has(connection.id)) {
        return;
      }
      await state.control.send(connection, message);
    }
  });
  return state.control.start();
}

async function startSocks(port = CONFIG.socksPort) {
  if (!CONFIG.localSocksEnabled) {
    return {
      enabled: false,
      running: false,
      host: "",
      port: 0,
      clients: 0,
      disabledReason: "local SOCKS listener is disabled in this build"
    };
  }
  if (state.socks && state.socks.getStatus().running) {
    return state.socks.getStatus();
  }
  state.socks = new SocksServer({
    host: CONFIG.socksHost,
    port,
    log
  });
  return state.socks.start();
}

async function stopSocks() {
  if (state.socks) {
    await state.socks.stop();
    state.socks = null;
  }
  return socksStatus();
}

async function handleControlMessage(request, connection) {
  const type = String(request.type || request.command || "status");
  try {
    switch (type) {
      case "ping":
        return {
          ok: true,
          type: "pong",
          now: new Date().toISOString()
        };
      case "status":
        return getStatus();
      case "logs":
        return {
          ok: true,
          logs: getLogText(request.limit)
        };
      case "tcp_probe": {
        const probe = await tcpProbe(request);
        log("tcp_probe result", probe);
        return probe;
      }
      case "start_socks": {
        const port = Number(request.port || CONFIG.socksPort);
        return {
          ok: Boolean(CONFIG.localSocksEnabled),
          socks: await startSocks(port)
        };
      }
      case "stop_socks":
        return {
          ok: true,
          socks: await stopSocks()
        };
      case "mythic_socks":
        return {
          ok: true,
          type: "mythic_socks_ack",
          mythicSocks: await state.mythicRelay.processMessages(request.socks || request.messages || [], connection)
        };
      case "mythic_socks_status":
        return {
          ok: true,
          mythicSocks: state.mythicRelay.getStatus()
        };
      case "mythic_socks_stop":
        await state.mythicRelay.closeAll(Boolean(request.notify));
        return {
          ok: true,
          mythicSocks: state.mythicRelay.getStatus()
        };
      default:
        return {
          ok: false,
          error: `unsupported command: ${type}`
        };
    }
  } catch (error) {
    state.lastError = String(error);
    log(`control command error: ${error}`);
    return {
      ok: false,
      error: String(error)
    };
  }
}

async function handshakeWithExtension() {
  if (!state.extensionId) {
    log("extension handshake skipped: no extension id in ?ext=");
    return null;
  }
  if (!globalThis.chrome || !chrome.runtime || typeof chrome.runtime.sendMessage !== "function") {
    log("extension handshake skipped: chrome.runtime.sendMessage unavailable");
    return null;
  }

  const payload = {
    type: "ditto.iwa.ready",
    app: "ditto-iwa",
    version: "0.1.0",
    controlUrl: `ws://${CONFIG.controlHost}:${CONFIG.controlPort}`,
    localSocksEnabled: Boolean(CONFIG.localSocksEnabled),
    socksHost: CONFIG.localSocksEnabled ? CONFIG.socksHost : "",
    socksPort: CONFIG.localSocksEnabled ? CONFIG.socksPort : 0,
    status: getStatus()
  };

  return new Promise((resolve) => {
    chrome.runtime.sendMessage(state.extensionId, payload, (response) => {
      const error = chrome.runtime.lastError;
      state.extensionHandshake = {
        ok: !error && Boolean(response && response.ok),
        error: error ? error.message : "",
        response: response || null,
        at: new Date().toISOString()
      };
      log("extension handshake result", state.extensionHandshake);
      resolve(state.extensionHandshake);
      updateUi();
    });
  });
}

async function initialize() {
  try {
    updateUi();
    await startControl();
    if (CONFIG.localSocksEnabled && CONFIG.autoStartSocks) {
      await startSocks(CONFIG.socksPort);
    }
    await handshakeWithExtension();
    log("initialized", getStatus());
    updateUi();
  } catch (error) {
    state.lastError = String(error);
    log(`initialization failed: ${error}`);
    updateUi();
  }
}

const startSocksButton = document.getElementById("startSocks");
const stopSocksButton = document.getElementById("stopSocks");
startSocksButton.disabled = !CONFIG.localSocksEnabled;
stopSocksButton.disabled = !CONFIG.localSocksEnabled;

startSocksButton.addEventListener("click", () => {
  startSocks(CONFIG.socksPort).catch((error) => {
    state.lastError = String(error);
    log(`start socks failed: ${error}`);
  });
});

stopSocksButton.addEventListener("click", () => {
  stopSocks().catch((error) => {
    state.lastError = String(error);
    log(`stop socks failed: ${error}`);
  });
});

document.getElementById("handshake").addEventListener("click", () => {
  handshakeWithExtension().catch((error) => {
    state.lastError = String(error);
    log(`handshake failed: ${error}`);
  });
});

initialize();
