(() => {
  "use strict";

  const inputLinkElement = document.querySelector("#input-link");
  const outputLinkElement = document.querySelector("#output-link");
  const outputRatioElement = document.querySelector("#output-ratio");
  const queryWarningElement = document.querySelector("#query-warning");
  const qrCodeImage = document.querySelector("#qrcode");
  const qrCodeCorrectionLevelContainer = document.querySelector("#qr-correct-level-container");
  const qrCodeCorrectionLevelElement = document.querySelector("#qr-correct-level");
  const transportSelect = document.querySelector("#settings-transport");
  const executionSelect = document.querySelector("#settings-execution");
  const codecStatusElement = document.querySelector("#codec-status");
  const qrSetting = document.querySelector("#settings-qr");
  const loader = document.querySelector("#loader");
  const content = document.querySelector("#content");
  const codecBootstrap = document.querySelector("#codec-bootstrap");
  const codecBootstrapMessage = document.querySelector("#codec-bootstrap-message");
  const codecBootstrapProgress = document.querySelector(".codec-bootstrap-progress");
  const codecBootstrapProgressFill = document.querySelector("#codec-bootstrap-progress-fill");
  const codecBootstrapPercent = document.querySelector("#codec-bootstrap-percent");
  const codecBootstrapStage = document.querySelector("#codec-bootstrap-stage");

  let updateVersion = 0;
  let clientInitialisation = null;
  let clientInitialisationError = null;
  let bootstrapVisible = false;
  let bootstrapHideTimer = null;
  let inputDebounceTimer = null;

  const inputDebounceDelay = () => (
    window.matchMedia("(pointer: coarse), (max-width: 640px)").matches ? 460 : 180
  );

  const api = async (endpoint, body) => {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || payload.detail || "Request failed");
    return payload;
  };

  const currentBaseLink = () => `${window.location.origin}${window.location.pathname}`;
  const usingClient = () => executionSelect.value === "client";

  function setVisibleApplication() {
    loader.style.opacity = 0;
    content.style.opacity = 1;
    content.style.pointerEvents = "auto";
  }

  function setCodecStatus(status) {
    // Worker precache progress can arrive after the codec has verified itself.
    // Ignore that late event rather than replacing the ready state in the UI.
    if (status.stage === "download" && window.HaMrBrowserCodec?.ready) {
      hideBootstrap();
      return;
    }
    const suffix = Number.isInteger(status.progress) ? ` ${status.progress}%` : "";
    codecStatusElement.textContent = `${status.message}${suffix}`;
    codecStatusElement.dataset.state = status.stage || "idle";
    updateBootstrap(status);
  }

  function showBootstrap() {
    if (bootstrapHideTimer) {
      window.clearTimeout(bootstrapHideTimer);
      bootstrapHideTimer = null;
    }
    if (bootstrapVisible) return;
    bootstrapVisible = true;
    codecBootstrap.hidden = false;
    codecBootstrap.setAttribute("aria-busy", "true");
    window.requestAnimationFrame(() => codecBootstrap.classList.add("is-visible"));
  }

  function hideBootstrap() {
    if (!bootstrapVisible) return;
    bootstrapVisible = false;
    codecBootstrap.classList.remove("is-visible");
    codecBootstrap.setAttribute("aria-busy", "false");
    bootstrapHideTimer = window.setTimeout(() => {
      if (!bootstrapVisible) codecBootstrap.hidden = true;
      bootstrapHideTimer = null;
    }, 280);
  }

  function updateBootstrap(status) {
    // A populated V26 Cache Storage cache reports only "cache" stages. The
    // full-screen view is deliberately reserved for a new runtime download.
    if (status.stage === "download") showBootstrap();
    if (!bootstrapVisible) return;

    const stagedProgress = { compile: 92, loader: 93, install: 96, verify: 99, ready: 100 };
    const progress = Number.isInteger(status.progress)
      ? status.progress
      : (stagedProgress[status.stage] ?? 0);
    const stageLabel = {
      download: "Downloading runtime",
      cache: "Reading saved runtime",
      manifest: "Checking codec assets",
      compile: "Starting WebAssembly",
      loader: "Loading Python runtime",
      install: "Installing V26 codec",
      verify: "Verifying compatibility",
      ready: "Ready",
      error: "Setup failed",
    }[status.stage] || "Preparing codec";

    codecBootstrapMessage.textContent = status.message;
    codecBootstrapStage.textContent = stageLabel;
    codecBootstrapPercent.textContent = `${progress}%`;
    codecBootstrapProgress.setAttribute("aria-valuenow", String(progress));
    codecBootstrapProgressFill.style.width = `${progress}%`;

    if (status.stage === "ready") hideBootstrap();
    if (status.stage === "error") hideBootstrap();
  }

  function updateQueryWarning(input) {
    try {
      const candidate = input.includes("://") ? input : `http://${input}`;
      const url = new URL(candidate);
      queryWarningElement.style.display = url.searchParams.size > 1 ? "inline" : "none";
    } catch (_) {
      queryWarningElement.style.display = "none";
    }
  }

  function resetOutput(message = "Enter a link above to compress") {
    outputLinkElement.textContent = message;
    outputLinkElement.removeAttribute("href");
    outputLinkElement.style.color = "";
    outputRatioElement.style.color = "rgba(255, 255, 255, 0)";
    queryWarningElement.style.display = "none";
    qrCodeImage.style.display = "none";
    qrCodeCorrectionLevelContainer.style.display = "none";
  }

  function showCodecError(message) {
    outputLinkElement.textContent = message;
    outputLinkElement.style.color = "rgb(255, 50, 50)";
    outputLinkElement.removeAttribute("href");
    outputRatioElement.style.color = "rgba(255, 255, 255, 0)";
    queryWarningElement.style.display = "none";
    qrCodeImage.style.display = "none";
    qrCodeCorrectionLevelContainer.style.display = "none";
  }

  function updateRatio(input, payload) {
    const normalised = input.replace(/^https?:\/\//, "");
    const ratio = (1 - (Array.from(payload).length + window.location.host.length) / Math.max(normalised.length, 1)) * 100;
    if (ratio < -300) {
      outputRatioElement.textContent = "Output is much larger than the input";
      outputRatioElement.style.color = "rgb(255, 50, 50)";
    } else if (ratio < 0) {
      outputRatioElement.textContent = `Output is ${Math.floor(-ratio)}% larger than the input`;
      outputRatioElement.style.color = "rgb(255, 50, 50)";
    } else if (ratio > 0) {
      outputRatioElement.textContent = `Output is ${Math.ceil(ratio)}% smaller than the input`;
      outputRatioElement.style.color = "rgb(15, 190, 15)";
    } else {
      outputRatioElement.textContent = "Output is the same length as the input";
      outputRatioElement.style.color = "gray";
    }
  }

  const QR_ERROR_LEVELS = ["L", "M", "Q", "H"];

  function showQr(image, link) {
    qrCodeImage.style.display = "inline";
    qrCodeCorrectionLevelContainer.style.display = "inline";
    qrCodeImage.src = image;
    qrCodeImage.title = link;
  }

  async function updateQr(input, version) {
    if (!qrSetting.checked) {
      qrCodeImage.style.display = "none";
      qrCodeCorrectionLevelContainer.style.display = "none";
      return;
    }

    const correctionLevel = Number(qrCodeCorrectionLevelElement.value);
    if (usingClient()) {
      if (!window.QRCode) throw new Error("Client QR encoder is unavailable.");
      if (!window.HaMrBrowserCodec.ready) throw new Error("Client-side V26 codec is still preparing.");
      // QR mode uses the exact browser V26 codec too, but its alphanumeric
      // transport produces a denser, more scanner-friendly path URL.
      const payload = window.HaMrBrowserCodec.compress(input, "qr");
      const qrBaseLink = currentBaseLink().replace(/\/$/, "").toUpperCase();
      const link = `${qrBaseLink}/${payload}`;
      const image = await window.QRCode.toDataURL(link, {
        errorCorrectionLevel: QR_ERROR_LEVELS[correctionLevel] || "M",
        width: 256,
        margin: 4,
      });
      if (version !== updateVersion) return;
      showQr(image, link);
      return;
    }

    // Server rendering is retained only for an explicitly selected server codec.
    const qrOutput = await api("/api/qr", { url: input, correction_level: correctionLevel });
    if (version !== updateVersion) return;
    showQr(qrOutput.image, qrOutput.link);
  }

  async function outputPayload(input, mode) {
    if (!usingClient()) {
      return (await api("/api/compress", { url: input, mode })).payload;
    }
    if (clientInitialisationError) throw clientInitialisationError;
    if (!window.HaMrBrowserCodec.ready) {
      throw new Error("Client-side V26 codec is still preparing.");
    }
    return window.HaMrBrowserCodec.compress(input, mode);
  }

  function cancelScheduledOutput() {
    if (inputDebounceTimer === null) return;
    window.clearTimeout(inputDebounceTimer);
    inputDebounceTimer = null;
  }

  function scheduleInputOutput() {
    cancelScheduledOutput();
    if (!inputLinkElement.value.trim()) {
      void updateOutput();
      return;
    }
    inputDebounceTimer = window.setTimeout(() => {
      inputDebounceTimer = null;
      void updateOutput();
    }, inputDebounceDelay());
  }

  async function updateOutput() {
    const version = ++updateVersion;
    const input = inputLinkElement.value.trim();
    if (!input) {
      resetOutput();
      return;
    }
    if (usingClient() && !window.HaMrBrowserCodec.ready) {
      resetOutput("Preparing client-side V26 codec…");
      return;
    }

    try {
      const payload = await outputPayload(input, transportSelect.value);
      if (version !== updateVersion) return;
      updateRatio(input, payload);
      const link = `${currentBaseLink()}#${payload}`;
      outputLinkElement.textContent = link;
      outputLinkElement.href = link;
      outputLinkElement.style.color = "";
      updateQueryWarning(input);
      await updateQr(input, version);
    } catch (error) {
      if (version !== updateVersion) return;
      showCodecError(error.message || "Invalid link");
      console.error(error);
    }
  }

  async function resolveFragment() {
    if (!window.location.hash) return false;
    const payload = decodeURIComponent(window.location.hash.slice(1)).replaceAll(" ", "");
    if (!payload.trim()) return false;
    if (!usingClient()) {
      const resolver = new URL("/resolve", window.location.origin);
      resolver.searchParams.set("payload", payload);
      window.location.replace(resolver);
      return true;
    }
    try {
      await ensureClientCodec();
      window.location.replace(window.HaMrBrowserCodec.decompressAuto(payload));
    } catch (error) {
      setCodecStatus({ stage: "error", message: "Client codec could not decode this link. Select server-side Python to retry." });
      setVisibleApplication();
      showCodecError("Client-side decoder is unavailable");
      console.error(error);
    }
    return true;
  }

  async function hasCachedClientCodec() {
    if (!("caches" in window)) return false;
    try {
      return (await caches.keys()).some((name) => name.startsWith("ha-mr-v26-"));
    } catch (_) {
      return false;
    }
  }

  async function registerCodecServiceWorker() {
    if (!("serviceWorker" in navigator)) return;
    try {
      await navigator.serviceWorker.register("/offline_sw.js", { scope: "/" });
    } catch (error) {
      console.warn("Browser codec asset cache worker could not register.", error);
    }
  }

  function ensureClientCodec() {
    if (clientInitialisation) return clientInitialisation;
    clientInitialisation = (async () => {
      try {
        // On a genuinely new browser, cover both the worker precache and the
        // runtime's own download with the prominent bootstrap screen.
        if (!await hasCachedClientCodec()) showBootstrap();
        await registerCodecServiceWorker();
        await window.HaMrBrowserCodec.initialise(setCodecStatus);
        clientInitialisationError = null;
        if (usingClient()) await updateOutput();
      } catch (error) {
        clientInitialisationError = error;
        setCodecStatus({ stage: "error", message: "Client codec unavailable. Server-side Python remains available." });
        if (usingClient() && inputLinkElement.value.trim()) showCodecError("Client-side codec failed to initialize");
        console.error(error);
        throw error;
      }
    })();
    return clientInitialisation;
  }

  async function initialise() {
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.addEventListener("message", (event) => {
        if (event.data?.type === "ha-mr-precache-progress") setCodecStatus(event.data);
      });
    }
    window.addEventListener("hashchange", () => { void resolveFragment(); });
    inputLinkElement.addEventListener("input", scheduleInputOutput);
    transportSelect.addEventListener("change", () => {
      cancelScheduledOutput();
      void updateOutput();
    });
    executionSelect.addEventListener("change", () => {
      cancelScheduledOutput();
      if (usingClient()) {
        if (window.HaMrBrowserCodec.ready) {
          setCodecStatus({ stage: "ready", message: "Client-side V26 codec ready.", progress: 100 });
        } else {
          void ensureClientCodec().catch(() => {});
        }
      } else {
        setCodecStatus({ stage: "server", message: "Server-side Python codec selected.", progress: null });
      }
      void updateOutput();
    });
    qrSetting.addEventListener("change", () => {
      cancelScheduledOutput();
      void updateOutput();
    });
    qrCodeCorrectionLevelElement.addEventListener("change", () => {
      cancelScheduledOutput();
      void updateOutput();
    });
    // A short fragment link stays on the default spinner until it redirects.
    // Ordinary visits reveal the interface immediately and prepare the codec in the background.
    if (await resolveFragment()) return;
    setVisibleApplication();
    void ensureClientCodec().catch(() => {});
    await updateOutput();
  }

  initialise();
})();
