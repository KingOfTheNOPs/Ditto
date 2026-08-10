import { base64ToBytes, bytesToBase64, decodeText } from "./codec.js";

const CONNECT_TIMEOUT_MS = 10000;

function openWithTimeout(socket, target) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      socket.close().catch(() => {});
      reject(new Error(`connect ${target.host}:${target.port} timed out after ${CONNECT_TIMEOUT_MS}ms`));
    }, CONNECT_TIMEOUT_MS);

    socket.opened.then(
      (open) => {
        clearTimeout(timer);
        resolve(open);
      },
      (error) => {
        clearTimeout(timer);
        reject(error);
      }
    );
  });
}

function ipv4(bytes) {
  return Array.from(bytes).join(".");
}

function ipv6(bytes) {
  const chunks = [];
  for (let i = 0; i < 16; i += 2) {
    chunks.push(((bytes[i] << 8) | bytes[i + 1]).toString(16));
  }
  return chunks.join(":");
}

function readPort(bytes, offset) {
  return (bytes[offset] << 8) | bytes[offset + 1];
}

function successReply() {
  return new Uint8Array([
    0x05, 0x00, 0x00, 0x01,
    0x00, 0x00, 0x00, 0x00,
    0x00, 0x00
  ]);
}

function failureReply() {
  return new Uint8Array([
    0x05, 0x01, 0x00, 0x01,
    0x00, 0x00, 0x00, 0x00,
    0x00, 0x00
  ]);
}

function parseConnectRequest(bytes) {
  if (bytes.length < 7 || bytes[0] !== 0x05 || bytes[1] !== 0x01) {
    throw new Error("invalid SOCKS5 CONNECT request");
  }

  let offset = 4;
  let host = "";
  if (bytes[3] === 0x01) {
    if (bytes.length < offset + 6) {
      throw new Error("truncated IPv4 SOCKS target");
    }
    host = ipv4(bytes.slice(offset, offset + 4));
    offset += 4;
  } else if (bytes[3] === 0x03) {
    const length = bytes[offset];
    offset += 1;
    if (bytes.length < offset + length + 2) {
      throw new Error("truncated domain SOCKS target");
    }
    host = decodeText(bytes.slice(offset, offset + length));
    offset += length;
  } else if (bytes[3] === 0x04) {
    if (bytes.length < offset + 18) {
      throw new Error("truncated IPv6 SOCKS target");
    }
    host = ipv6(bytes.slice(offset, offset + 16));
    offset += 16;
  } else {
    throw new Error(`unsupported SOCKS address type ${bytes[3]}`);
  }

  const port = readPort(bytes, offset);
  offset += 2;
  return {
    host,
    port,
    payload: bytes.slice(offset)
  };
}

export class MythicSocksRelay {
  constructor({ emit, log }) {
    this.emit = emit;
    this.log = log;
    this.connections = new Map();
  }

  async processMessages(messages, connection) {
    for (const message of messages) {
      await this.processMessage(message, connection);
    }
    return this.getStatus();
  }

  async processMessage(message, controlConnection) {
    const serverId = Number(message.server_id ?? message.serverId);
    if (!Number.isFinite(serverId)) {
      return;
    }

    const existing = this.connections.get(serverId);
    const data = message.data ? base64ToBytes(message.data) : new Uint8Array(0);
    if (message.exit) {
      if (existing && data.length) {
        await existing.writer.write(data);
      }
      await this.close(serverId, false);
      return;
    }

    if (existing) {
      if (data.length) {
        await existing.writer.write(data);
      }
      return;
    }

    await this.open(serverId, data, controlConnection);
  }

  async open(serverId, requestBytes, controlConnection) {
    let remote = null;
    let reader = null;
    let writer = null;
    let target = null;

    try {
      target = parseConnectRequest(requestBytes);
      remote = new TCPSocket(target.host, target.port);
      const open = await openWithTimeout(remote, target);
      reader = open.readable.getReader();
      writer = open.writable.getWriter();
      this.connections.set(serverId, {
        remote,
        reader,
        writer,
        controlConnection
      });

      await this.sendToExtension(controlConnection, serverId, successReply(), false);
      if (target.payload.length) {
        await writer.write(target.payload);
      }

      this.readLoop(serverId, reader, controlConnection).catch((error) => {
        this.log(`mythic socks ${serverId} read error: ${error.message}`);
        this.close(serverId, true).catch(() => {});
      });
      this.log(`mythic socks ${serverId} connected ${target.host}:${target.port}`);
    } catch (error) {
      const destination = target ? ` ${target.host}:${target.port}` : "";
      this.log(`mythic socks ${serverId}${destination} connect failed: ${error.message}`);
      await this.sendToExtension(controlConnection, serverId, failureReply(), false);
      await this.sendToExtension(controlConnection, serverId, new Uint8Array(0), true);
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
        if (remote) {
          await remote.close();
        }
      } catch (_) {
      }
    }
  }

  async readLoop(serverId, reader, controlConnection) {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }
      const bytes = value instanceof Uint8Array ? value : new Uint8Array(value);
      await this.sendToExtension(controlConnection, serverId, bytes, false);
    }
    await this.close(serverId, true);
  }

  async sendToExtension(connection, serverId, data, exit) {
    await this.emit(connection, {
      type: "mythic_socks",
      socks: [
        {
          server_id: serverId,
          exit: Boolean(exit),
          data: data.length ? bytesToBase64(data) : ""
        }
      ]
    });
  }

  async close(serverId, notify) {
    const state = this.connections.get(serverId);
    if (!state) {
      return;
    }
    this.connections.delete(serverId);
    try {
      state.reader.releaseLock();
    } catch (_) {
    }
    try {
      state.writer.releaseLock();
    } catch (_) {
    }
    try {
      await state.remote.close();
    } catch (_) {
    }
    if (notify) {
      await this.sendToExtension(state.controlConnection, serverId, new Uint8Array(0), true);
    }
    this.log(`mythic socks ${serverId} closed`);
  }

  async closeAll(notify = false) {
    for (const serverId of [...this.connections.keys()]) {
      await this.close(serverId, notify);
    }
  }

  getStatus() {
    return {
      running: true,
      connections: this.connections.size
    };
  }
}
