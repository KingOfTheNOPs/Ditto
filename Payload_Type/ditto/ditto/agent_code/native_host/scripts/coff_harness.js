const crypto = require("crypto");
const fs = require("fs");
const { spawn } = require("child_process");

function b64url(buffer) {
  return Buffer.from(buffer)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/g, "");
}

function fromB64url(value) {
  const normalized = String(value).replace(/-/g, "+").replace(/_/g, "/");
  return Buffer.from(normalized + "=".repeat((4 - (normalized.length % 4)) % 4), "base64");
}

function encrypt(key, payload) {
  const nonce = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv("aes-256-gcm", key, nonce);
  const ciphertext = Buffer.concat([cipher.update(Buffer.from(JSON.stringify(payload), "utf8")), cipher.final()]);
  const tag = cipher.getAuthTag();
  return {
    v: 1,
    k: "a1",
    n: b64url(nonce),
    d: b64url(Buffer.concat([ciphertext, tag])),
  };
}

function decrypt(key, envelope) {
  const nonce = fromB64url(envelope.n);
  const data = fromB64url(envelope.d);
  const ciphertext = data.subarray(0, data.length - 16);
  const tag = data.subarray(data.length - 16);
  const decipher = crypto.createDecipheriv("aes-256-gcm", key, nonce);
  decipher.setAuthTag(tag);
  return JSON.parse(Buffer.concat([decipher.update(ciphertext), decipher.final()]).toString("utf8"));
}

function frame(value) {
  const body = Buffer.from(JSON.stringify(value), "utf8");
  const len = Buffer.alloc(4);
  len.writeUInt32LE(body.length, 0);
  return Buffer.concat([len, body]);
}

function parseFrame(buffer) {
  if (buffer.length < 4) {
    return null;
  }
  const len = buffer.readUInt32LE(0);
  if (len === 0 || len > 16 * 1024 * 1024 || buffer.length < len + 4) {
    return null;
  }
  return JSON.parse(buffer.subarray(4, 4 + len).toString("utf8"));
}

function parseArgs(argv) {
  const out = {
    key: "c7+Vhc2xfM+SOXHFrg9thzVKJKgLsQaF+TyoyH7cNdA=",
    function: "go",
    timeout: 15000,
    args: {},
  };
  for (let idx = 2; idx < argv.length; idx += 1) {
    const arg = argv[idx];
    const next = () => argv[++idx];
    if (arg === "--exe") out.exe = next();
    else if (arg === "--bof") out.bof = next();
    else if (arg === "--key") out.key = next();
    else if (arg === "--function") out.function = next();
    else if (arg === "--timeout") out.timeout = Number(next());
    else if (arg === "--args-json") out.args = JSON.parse(next());
    else if (arg === "--args-file") out.args = JSON.parse(fs.readFileSync(next(), "utf8"));
    else throw new Error(`unknown argument: ${arg}`);
  }
  if (!out.exe || !out.bof) {
    throw new Error("usage: node coff_harness.js --exe <host.exe> --bof <file.x64.o> [--args-json <json>]");
  }
  return out;
}

async function main() {
  const opts = parseArgs(process.argv);
  const key = Buffer.from(opts.key, "base64");
  if (key.length !== 32) {
    throw new Error("key must decode to 32 bytes");
  }
  const request = {
    id: crypto.randomUUID(),
    c: "coffexec",
    a: {
      coff_source: "new",
      coff_b64: fs.readFileSync(opts.bof).toString("base64"),
      function: opts.function,
      ...opts.args,
    },
  };
  const child = spawn(opts.exe, [], { stdio: ["pipe", "pipe", "pipe"], windowsHide: true });
  const stdout = [];
  const stderr = [];
  child.stdout.on("data", (chunk) => stdout.push(chunk));
  child.stderr.on("data", (chunk) => stderr.push(chunk));

  const done = new Promise((resolve) => {
    child.on("exit", (code, signal) => resolve({ code, signal }));
  });

  child.stdin.write(frame(encrypt(key, request)));
  child.stdin.end();

  const timer = setTimeout(() => child.kill(), opts.timeout);
  const exit = await done;
  clearTimeout(timer);

  const output = Buffer.concat(stdout);
  const envelope = parseFrame(output);
  if (!envelope) {
    console.log(JSON.stringify({
      ok: false,
      exit,
      stderr: Buffer.concat(stderr).toString("utf8"),
      stdout_len: output.length,
    }, null, 2));
    process.exitCode = 2;
    return;
  }
  console.log(JSON.stringify({
    exit,
    response: decrypt(key, envelope),
    stderr: Buffer.concat(stderr).toString("utf8"),
  }, null, 2));
}

main().catch((error) => {
  console.error(error.stack || String(error));
  process.exitCode = 1;
});
