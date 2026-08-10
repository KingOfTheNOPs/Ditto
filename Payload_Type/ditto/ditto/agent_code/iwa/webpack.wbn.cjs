const fs = require("fs");
const path = require("path");
const HtmlWebpackPlugin = require("html-webpack-plugin");
const WebBundlePlugin = require("webbundle-webpack-plugin");
const { WebBundleId, parsePemKey } = require("wbn-sign");

const privateKeyPath = path.resolve(__dirname, "private-ecdsa-p256.key");
if (!fs.existsSync(privateKeyPath)) {
  throw new Error("private-ecdsa-p256.key is missing; run npm run generate-keys first");
}

const parsedPrivateKey = parsePemKey(fs.readFileSync(privateKeyPath));
const baseURL = new WebBundleId(parsedPrivateKey).serializeWithIsolatedWebAppOrigin();

module.exports = {
  mode: "production",
  entry: "./src/bundle-entry.js",
  output: {
    filename: "bundle.js",
    path: path.resolve(__dirname, "dist-wbn"),
    clean: true
  },
  module: {
    rules: [
      {
        test: /\.css$/i,
        use: ["style-loader", "css-loader"]
      }
    ]
  },
  plugins: [
    new HtmlWebpackPlugin({
      template: "src/index.wbn.html",
      filename: "index.html",
      scriptLoading: "defer"
    }),
    new WebBundlePlugin({
      baseURL,
      static: {
        dir: "public"
      },
      output: "app.swbn",
      headerOverride: {
        "permissions-policy": "direct-sockets=(self), direct-sockets-private=(self), local-network=(self), loopback-network=(self)"
      },
      integrityBlockSign: {
        key: parsedPrivateKey
      }
    })
  ]
};
