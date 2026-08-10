import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { SignedWebBundle } from "wbn-sign";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, "..");
const bundlePath = path.join(rootDir, "dist-wbn", "app.swbn");
const outputDir = path.join(rootDir, "install-artifacts");
const outputPath = path.join(outputDir, "bundle-info.json");

const signedBundle = SignedWebBundle.fromBytes(fs.readFileSync(bundlePath));
const signatureStack = signedBundle.getIntegrityBlock().getSignatureStack();
if (!signatureStack.length) {
  throw new Error("Signed web bundle has no integrity signatures");
}

const signature = signatureStack[0];
const [keyType, publicKey] = Object.entries(signature.signatureAttributes)[0];
const bundleInfo = {
  web_bundle_id: signedBundle.getWebBundleId(),
  key_type: keyType.replace(/PublicKey$/, ""),
  public_key: Buffer.from(publicKey).toString("base64"),
  signature_hex: Buffer.from(signature.signature).toString("hex")
};

fs.mkdirSync(outputDir, { recursive: true });
fs.writeFileSync(outputPath, `${JSON.stringify(bundleInfo, null, 2)}\n`);
console.log(`BUNDLE_INFO=${outputPath}`);
