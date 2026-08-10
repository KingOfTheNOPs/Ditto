import { concatBytes, decodeText, encodeText } from "./codec.js";

const WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";

async function sha1Base64(value) {
  const hash = await crypto.subtle.digest("SHA-1", encodeText(value));
  return btoa(String.fromCharCode(...new Uint8Array(hash)));
}

function parseHeaderText(text) {
  const headers = {};
  for (const line of text.split("\r\n").slice(1)) {
    const index = line.indexOf(":");
    if (index === -1) {
      continue;
    }
    headers[line.slice(0, index).trim().toLowerCase()] = line.slice(index + 1).trim();
  }
  return headers;
}

function encodeFrame(text) {
  const payload = encodeText(text);
  if (payload.length < 126) {
    return concatBytes(new Uint8Array([0x81, payload.length]), payload);
  }
  if (payload.length <= 0xffff) {
    return concatBytes(
      new Uint8Array([0x81, 126, (payload.length >> 8) & 0xff, payload.length & 0xff]),
      payload
    );
  }
  const header = new Uint8Array(10);
  header[0] = 0x81;
  header[1] = 127;
  const view = new DataView(header.buffer);
  view.setUint32(2, 0);
  view.setUint32(6, payload.length);
  return concatBytes(header, payload);
}

function decodeFrames(buffer) {
  const frames = [];
  let offset = 0;

  while (offset + 2 <= buffer.length) {
    const first = buffer[offset];
    const second = buffer[offset + 1];
    const opcode = first & 0x0f;
    const masked = Boolean(second & 0x80);
    let length = second & 0x7f;
    let headerLength = 2;

    if (length === 126) {
      if (offset + 4 > buffer.length) {
        break;
      }
      length = (buffer[offset + 2] << 8) | buffer[offset + 3];
      headerLength = 4;
    } else if (length === 127) {
      if (offset + 10 > buffer.length) {
        break;
      }
      const view = new DataView(buffer.buffer, buffer.byteOffset + offset + 2, 8);
      const high = view.getUint32(0);
      const low = view.getUint32(4);
      if (high !== 0) {
        throw new Error("websocket frame too large");
      }
      length = low;
      headerLength = 10;
    }

    const maskLength = masked ? 4 : 0;
    const frameLength = headerLength + maskLength + length;
    if (offset + frameLength > buffer.length) {
      break;
    }

    let payload = buffer.slice(offset + headerLength + maskLength, offset + frameLength);
    if (masked) {
      const mask = buffer.slice(offset + headerLength, offset + headerLength + 4);
      payload = payload.map((byte, index) => byte ^ mask[index % 4]);
    }

    frames.push({
      opcode,
      text: opcode === 1 ? decodeText(payload) : "",
      raw: payload
    });

    offset += frameLength;
  }

  return {
    frames,
    remaining: buffer.slice(offset)
  };
}

export class WebSocketServer {
  constructor({ host, port, onMessage, log }) {
    this.host = host;
    this.port = port;
    this.onMessage = onMessage;
    this.log = log;
    this.serverSocket = null;
    this.connections = new Map();
    this.nextId = 1;
    this.running = false;
    this.openInfo = null;
  }

  async start() {
    if (this.running) {
      return this.getStatus();
    }
    if (!("TCPServerSocket" in globalThis)) {
      throw new Error("Direct Sockets TCPServerSocket is not available");
    }

    this.serverSocket = new TCPServerSocket(this.host, {
      localPort: this.port
    });
    this.openInfo = await this.serverSocket.opened;
    this.running = true;
    this.acceptLoop(this.openInfo.readable).catch((error) => this.log(`control accept error: ${error}`));
    this.log(`control websocket listening on ${this.openInfo.localAddress}:${this.openInfo.localPort}`);
    return this.getStatus();
  }

  async acceptLoop(readable) {
    const reader = readable.getReader();
    try {
      while (this.running) {
        const { value: socket, done } = await reader.read();
        if (done) {
          break;
        }
        this.handleSocket(socket, this.nextId++).catch((error) => this.log(`control client error: ${error}`));
      }
    } finally {
      reader.releaseLock();
    }
  }

  async handleSocket(socket, id) {
    const open = await socket.opened;
    const connection = {
      id,
      socket,
      open,
      reader: open.readable.getReader(),
      writer: open.writable.getWriter(),
      buffer: new Uint8Array(0),
      websocket: false
    };
    this.connections.set(id, connection);
    this.log(`control client ${id} connected`);

    try {
      while (this.running && this.connections.has(id)) {
        const { value, done } = await connection.reader.read();
        if (done) {
          break;
        }
        await this.handleBytes(connection, value instanceof Uint8Array ? value : new Uint8Array(value));
      }
    } finally {
      await this.closeConnection(id);
    }
  }

  async handleBytes(connection, bytes) {
    connection.buffer = concatBytes(connection.buffer, bytes);

    if (!connection.websocket) {
      const text = decodeText(connection.buffer);
      const headerEnd = text.indexOf("\r\n\r\n");
      if (headerEnd === -1) {
        return;
      }
      const headerText = text.slice(0, headerEnd + 4);
      const headers = parseHeaderText(headerText);
      const key = headers["sec-websocket-key"];
      if (!key) {
        throw new Error("missing Sec-WebSocket-Key");
      }
      const accept = await sha1Base64(`${key}${WS_GUID}`);
      const response = [
        "HTTP/1.1 101 Switching Protocols",
        "Upgrade: websocket",
        "Connection: Upgrade",
        `Sec-WebSocket-Accept: ${accept}`,
        "",
        ""
      ].join("\r\n");
      await connection.writer.write(encodeText(response));
      connection.websocket = true;
      connection.buffer = connection.buffer.slice(headerEnd + 4);
      this.log(`control client ${connection.id} websocket ready`);
    }

    const parsed = decodeFrames(connection.buffer);
    connection.buffer = parsed.remaining;
    for (const frame of parsed.frames) {
      if (frame.opcode === 8) {
        await this.closeConnection(connection.id);
        continue;
      }
      if (frame.opcode !== 1) {
        continue;
      }
      await this.dispatchMessage(connection, frame.text);
    }
  }

  async dispatchMessage(connection, text) {
    let request;
    try {
      request = JSON.parse(text);
    } catch (error) {
      await this.send(connection, {
        ok: false,
        error: `invalid json: ${error.message}`
      });
      return;
    }

    const response = await this.onMessage(request, connection);
    await this.send(connection, response);
  }

  async send(connection, message) {
    const payload = JSON.stringify(message);
    await connection.writer.write(encodeFrame(payload));
  }

  async broadcast(message) {
    for (const connection of this.connections.values()) {
      if (connection.websocket) {
        await this.send(connection, message);
      }
    }
  }

  async closeConnection(id) {
    const connection = this.connections.get(id);
    if (!connection) {
      return;
    }
    this.connections.delete(id);
    try {
      connection.reader.releaseLock();
    } catch (_) {
    }
    try {
      connection.writer.releaseLock();
    } catch (_) {
    }
    try {
      await connection.socket.close();
    } catch (_) {
    }
    this.log(`control client ${id} closed`);
  }

  async stop() {
    this.running = false;
    for (const id of [...this.connections.keys()]) {
      await this.closeConnection(id);
    }
    if (this.serverSocket) {
      await this.serverSocket.close();
      this.serverSocket = null;
    }
    this.openInfo = null;
  }

  getStatus() {
    return {
      running: this.running,
      host: this.openInfo ? this.openInfo.localAddress : this.host,
      port: this.openInfo ? this.openInfo.localPort : this.port,
      clients: this.connections.size
    };
  }
}
