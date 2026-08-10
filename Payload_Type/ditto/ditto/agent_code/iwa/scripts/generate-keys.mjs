import { generateKeyPairSync } from "crypto";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { WebBundleId, parsePemKey } from "wbn-sign";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, "..");
const privateKeyPath = path.join(rootDir, "private-ecdsa-p256.key");

if (!fs.existsSync(privateKeyPath)) {
  const { privateKey } = generateKeyPairSync("ec", {
    namedCurve: "prime256v1"
  });
  fs.writeFileSync(
    privateKeyPath,
    privateKey.export({
      type: "sec1",
      format: "pem"
    })
  );
  console.log(`Generated ${privateKeyPath}`);
}

const parsedKey = parsePemKey(fs.readFileSync(privateKeyPath));
const isolatedOrigin = new WebBundleId(parsedKey).serializeWithIsolatedWebAppOrigin();
console.log(`IWA_ORIGIN=${isolatedOrigin}`);
