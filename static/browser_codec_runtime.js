(() => {
  "use strict";

  const MANIFEST_URL = "/static/codec/v26/manifest.json";
  const PYODIDE_SCRIPT = "/static/pyodide/0.26.3/pyodide.js";

  class BrowserCodecError extends Error {}

  class BrowserV26Codec {
    constructor() {
      this._initPromise = null;
      this._ready = false;
      this._pyodide = null;
      this.revision = null;
    }

    get ready() {
      return this._ready;
    }

    async initialise(onStatus = () => {}) {
      if (!this._initPromise) {
        this._initPromise = this._initialise(onStatus).catch((error) => {
          this._initPromise = null;
          this._ready = false;
          throw error;
        });
      }
      return this._initPromise;
    }

    async _initialise(onStatus) {
      onStatus({ stage: "manifest", message: "Checking the exact V26 browser codec…", progress: 0 });
      const manifestResponse = await fetch(MANIFEST_URL, { cache: "no-cache" });
      if (!manifestResponse.ok) throw new BrowserCodecError("The browser codec manifest could not be loaded.");
      const manifest = await manifestResponse.json();
      this.revision = manifest.codec.revision;
      const cache = await caches.open(manifest.cache_name);
      const assets = [...manifest.runtime_assets, manifest.codec.archive, manifest.codec.conformance];
      const totalBytes = assets.reduce((total, asset) => total + asset.bytes, 0);
      let completedBytes = 0;

      for (const asset of assets) {
        const cached = await cache.match(asset.url);
        if (cached) {
          completedBytes += asset.bytes;
          onStatus({
            stage: "cache",
            message: "Using cached frozen runtime assets…",
            progress: Math.round((completedBytes / totalBytes) * 100),
            cached: true,
          });
          continue;
        }
        onStatus({
          stage: "download",
          message: `Downloading browser codec assets… ${this._formatBytes(completedBytes)} / ${this._formatBytes(totalBytes)}`,
          progress: Math.round((completedBytes / totalBytes) * 100),
          cached: false,
        });
        const response = await fetch(asset.url, { cache: "no-store" });
        if (!response.ok || !response.body) throw new BrowserCodecError(`Failed to download ${asset.url}.`);
        const reader = response.body.getReader();
        const chunks = [];
        let assetBytes = 0;
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          chunks.push(value);
          assetBytes += value.byteLength;
          const current = Math.min(totalBytes, completedBytes + assetBytes);
          onStatus({
            stage: "download",
            message: `Downloading browser codec assets… ${this._formatBytes(current)} / ${this._formatBytes(totalBytes)}`,
            progress: Math.round((current / totalBytes) * 100),
            cached: false,
          });
        }
        const blob = new Blob(chunks, { type: response.headers.get("content-type") || "application/octet-stream" });
        await cache.put(asset.url, new Response(blob, { headers: { "content-type": blob.type } }));
        completedBytes += asset.bytes;
      }

      await this._loadPyodideScript(cache, onStatus);
      onStatus({ stage: "compile", message: "Compiling and initializing WebAssembly…", progress: null });
      const indexURL = new URL(manifest.runtime.index_url, window.location.origin).href;
      this._pyodide = await window.loadPyodide({ indexURL });

      onStatus({ stage: "install", message: "Installing frozen V26 codec tables…", progress: null });
      const archiveResponse = await cache.match(manifest.codec.archive.url);
      this._pyodide.unpackArchive(await archiveResponse.arrayBuffer(), "zip", { extractDir: "/home/pyodide" });
      this._pyodide.runPython("from browser_codec_bridge import compress_url, decompress_payload, decompress_auto");

      onStatus({ stage: "verify", message: "Verifying exact V26 payload compatibility…", progress: null });
      const conformanceResponse = await cache.match(manifest.codec.conformance.url);
      await this._verify(await conformanceResponse.json());
      await this._discardSupersededCaches(manifest.cache_name);
      this._ready = true;
      onStatus({ stage: "ready", message: "Client-side V26 codec ready.", progress: 100 });
      return this;
    }

    async _loadPyodideScript(cache, onStatus) {
      if (window.loadPyodide) return;
      onStatus({ stage: "loader", message: "Starting the browser Python runtime…", progress: null });
      if (!await cache.match(PYODIDE_SCRIPT)) throw new BrowserCodecError("Pinned WebAssembly runtime loader is missing from cache.");
      await new Promise((resolve, reject) => {
        const script = document.createElement("script");
        script.src = PYODIDE_SCRIPT;
        script.async = true;
        script.onload = resolve;
        script.onerror = () => reject(new BrowserCodecError("Browser Python runtime loader failed to start."));
        document.head.appendChild(script);
      });
      if (!window.loadPyodide) throw new BrowserCodecError("Browser Python runtime did not expose its loader.");
    }

    async _verify(conformance) {
      for (const vector of conformance.vectors) {
        for (const [mode, expected] of Object.entries(vector.payloads)) {
          const actual = this._call("compress_url", vector.url, mode);
          if (actual !== expected) throw new BrowserCodecError(`Exact V26 verification failed for ${mode} transport.`);
          const restored = this._call("decompress_payload", actual, mode);
          if (restored !== vector.url) throw new BrowserCodecError(`V26 round-trip verification failed for ${mode} transport.`);
        }
      }
      const historical = conformance.historical_decode;
      if (this._call("decompress_payload", historical.payload, historical.mode) !== historical.url) {
        throw new BrowserCodecError("Historical adaptive payload verification failed.");
      }
    }

    _call(functionName, first, second) {
      if (!this._pyodide) throw new BrowserCodecError("Client codec is not initialized.");
      this._pyodide.globals.set("_ha_browser_first", first);
      this._pyodide.globals.set("_ha_browser_second", second);
      try {
        const result = this._pyodide.runPython(`${functionName}(_ha_browser_first, _ha_browser_second)`);
        return String(result);
      } catch (error) {
        throw new BrowserCodecError(error?.message || "Browser codec failed.");
      } finally {
        this._pyodide.globals.delete("_ha_browser_first");
        this._pyodide.globals.delete("_ha_browser_second");
      }
    }

    compress(url, mode) {
      return this._call("compress_url", url, mode);
    }

    decompress(payload, mode) {
      return this._call("decompress_payload", payload, mode);
    }

    decompressAuto(payload) {
      if (!this._pyodide) throw new BrowserCodecError("Client codec is not initialized.");
      this._pyodide.globals.set("_ha_browser_payload", payload);
      try {
        return String(this._pyodide.runPython("decompress_auto(_ha_browser_payload)"));
      } catch (error) {
        throw new BrowserCodecError(error?.message || "Browser codec failed.");
      } finally {
        this._pyodide.globals.delete("_ha_browser_payload");
      }
    }

    async _discardSupersededCaches(currentName) {
      const names = await caches.keys();
      await Promise.all(names
        .filter((name) => name.startsWith("ha-mr-v26-") && name !== currentName)
        .map((name) => caches.delete(name)));
    }

    _formatBytes(value) {
      return `${(value / 1024 / 1024).toFixed(value >= 1024 * 1024 ? 1 : 2)} MB`;
    }
  }

  window.HaMrBrowserCodec = new BrowserV26Codec();
  window.HaMrBrowserCodecError = BrowserCodecError;
})();
