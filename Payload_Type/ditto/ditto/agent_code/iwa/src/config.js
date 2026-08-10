const query = new URLSearchParams(location.search);

export const CONFIG = Object.freeze({
  controlHost: "127.0.0.1",
  controlPort: 38899,
  localSocksEnabled: false,
  socksHost: "",
  socksPort: 0,
  autoStartSocks: false,
  bridgeExtensionId: query.get("ext") || "efaidnbmnnnibpcajpcglclefindmkaj",
  debugUi: query.get("debug") === "1" || false
});
