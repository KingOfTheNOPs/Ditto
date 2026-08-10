import { concatBytes, decodeText } from "./codec.js";

const CONNECT_TIMEOUT_MS = 8000;

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

async function pipe(reader, writer, label, log) {
  let total = 0;
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }
      total += value.length;
      await writer.write(value);
    }
  } catch (error) {
    log(`${label} pipe ended: ${error.message}`);
  } finally {
    log(`${label} pipe transferred ${total} bytes`);
  }
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

class BufferedReader {
  constructor(reader) {
    this.reader = reader;
    this.buffer = new Uint8Array(0);
  }

  async read(needed) {
    while (this.buffer.length < needed) {
      const { value, done } = await this.reader.read();
      if (done) {
        throw new Error("socket closed while reading SOCKS request");
      }
      this.buffer = concatBytes(this.buffer, value);
    }
    const out = this.buffer.slice(0, needed);
    this.buffer = this.buffer.slice(needed);
    return out;
  }

  takeBuffered() {
    const out = this.buffer;
    this.buffer = new Uint8Array(0);
    return out;
  }
}

export class SocksServer {
  constructor({ host, port, log }) {
    this.host = host;
    this.port = port;
    this.log = log;
    this.serverSocket = null;
    this.openInfo = null;
    this.running = false;
    this.connections = new Map();
    this.nextId = 1;
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
    this.acceptLoop(this.openInfo.readable).catch((error) => this.log(`socks accept error: ${error}`));
    this.log(`socks listening on ${this.openInfo.localAddress}:${this.openInfo.localPort}`);
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
        this.handleClient(socket, this.nextId++).catch((error) => this.log(`socks client error: ${error}`));
      }
    } finally {
      reader.releaseLock();
    }
  }

  async handleClient(client, id) {
    const clientOpen = await client.opened;
    const clientReader = clientOpen.readable.getReader();
    const bufferedReader = new BufferedReader(clientReader);
    const clientWriter = clientOpen.writable.getWriter();
    let remote = null;
    const connection = {
      client,
      remote,
      target: "",
      phase: "accepted",
      startedAt: new Date().toISOString()
    };
    this.connections.set(id, connection);
    this.log(`socks client ${id} connected`);

    try {
      connection.phase = "greeting";
      const hello = await bufferedReader.read(2);
      if (hello[0] !== 0x05) {
        throw new Error("unsupported SOCKS version");
      }
      const methods = await bufferedReader.read(hello[1]);
      if (!methods.includes(0x00)) {
        await clientWriter.write(new Uint8Array([0x05, 0xff]));
        throw new Error("client did not offer no-auth");
      }
      await clientWriter.write(new Uint8Array([0x05, 0x00]));

      connection.phase = "request";
      const head = await bufferedReader.read(4);
      if (head[0] !== 0x05 || head[1] !== 0x01) {
        throw new Error("only SOCKS5 CONNECT is supported");
      }

      const target = await this.readTarget(bufferedReader, head[3]);
      connection.target = `${target.host}:${target.port}`;
      connection.phase = "connecting";
      this.log(`socks client ${id} connect ${target.host}:${target.port}`);

      remote = new TCPSocket(target.host, target.port);
      connection.remote = remote;
      const remoteOpen = await withTimeout(
        remote.opened,
        CONNECT_TIMEOUT_MS,
        `TCPSocket ${target.host}:${target.port}`,
        async () => {
          try {
            await remote.close();
          } catch (_) {
          }
        }
      );
      connection.phase = "connected";
      this.log(`socks client ${id} connected ${target.host}:${target.port}`);

      await clientWriter.write(new Uint8Array([
        0x05, 0x00, 0x00, 0x01,
        0x00, 0x00, 0x00, 0x00,
        0x00, 0x00
      ]));

      const remoteReader = remoteOpen.readable.getReader();
      const remoteWriter = remoteOpen.writable.getWriter();
      const initialPayload = bufferedReader.takeBuffered();
      if (initialPayload.length) {
        await remoteWriter.write(initialPayload);
      }
      await Promise.race([
        pipe(clientReader, remoteWriter, `socks ${id} client->remote`, this.log),
        pipe(remoteReader, clientWriter, `socks ${id} remote->client`, this.log)
      ]);
    } catch (error) {
      this.log(`socks client ${id} error: ${error.message}`);
      try {
        await clientWriter.write(new Uint8Array([
          0x05, 0x01, 0x00, 0x01,
          0x00, 0x00, 0x00, 0x00,
          0x00, 0x00
        ]));
      } catch (_) {
      }
    } finally {
      this.connections.delete(id);
      try {
        clientReader.releaseLock();
      } catch (_) {
      }
      try {
        clientWriter.releaseLock();
      } catch (_) {
      }
      try {
        await client.close();
      } catch (_) {
      }
      try {
        if (remote) {
          await remote.close();
        }
      } catch (_) {
      }
      this.log(`socks client ${id} closed`);
    }
  }

  async readTarget(reader, atyp) {
    if (atyp === 0x01) {
      const bytes = await reader.read(6);
      return {
        host: ipv4(bytes.slice(0, 4)),
        port: readPort(bytes, 4)
      };
    }
    if (atyp === 0x03) {
      const lenBytes = await reader.read(1);
      const bytes = await reader.read(lenBytes[0] + 2);
      return {
        host: decodeText(bytes.slice(0, lenBytes[0])),
        port: readPort(bytes, lenBytes[0])
      };
    }
    if (atyp === 0x04) {
      const bytes = await reader.read(18);
      return {
        host: ipv6(bytes.slice(0, 16)),
        port: readPort(bytes, 16)
      };
    }
    throw new Error(`unsupported address type ${atyp}`);
  }

  async stop() {
    this.running = false;
    if (this.serverSocket) {
      await this.serverSocket.close();
      this.serverSocket = null;
    }
    for (const { client, remote } of this.connections.values()) {
      try {
        await client.close();
      } catch (_) {
      }
      try {
        if (remote) {
          await remote.close();
        }
      } catch (_) {
      }
    }
    this.connections.clear();
    this.openInfo = null;
  }

  getStatus() {
    return {
      running: this.running,
      host: this.openInfo ? this.openInfo.localAddress : this.host,
      port: this.openInfo ? this.openInfo.localPort : this.port,
      clients: this.connections.size,
      active: [...this.connections.entries()].map(([id, connection]) => ({
        id,
        target: connection.target,
        phase: connection.phase,
        startedAt: connection.startedAt
      }))
    };
  }
}
