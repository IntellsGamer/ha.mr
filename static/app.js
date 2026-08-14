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

  let updateVersion = 0;
  let clientInitialisation = null;
  let clientInitialisationError = null;

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
    const suffix = Number.isInteger(status.progress) ? ` ${status.progress}%` : "";
    codecStatusElement.textContent = `${status.message}${suffix}`;
    codecStatusElement.dataset.state = status.stage || "idle";
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

  async function updateQr(input, version) {
    if (!qrSetting.checked) {
      qrCodeImage.style.display = "none";
      qrCodeCorrectionLevelContainer.style.display = "none";
      return;
    }
    // QR rendering remains a server-rendered image, but the server invokes the
    // same V26 codec and therefore produces the same encoded destination.
    const qrOutput = await api("/api/qr", {
      url: input,
      correction_level: Number(qrCodeCorrectionLevelElement.value),
    });
    if (version !== updateVersion) return;
    qrCodeImage.style.display = "inline";
    qrCodeCorrectionLevelContainer.style.display = "inline";
    qrCodeImage.src = qrOutput.image;
    qrCodeImage.title = qrOutput.link;
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
      showCodecError("Client-side decoder is unavailable");
      console.error(error);
    }
    return true;
  }

  async function registerCodecServiceWorker() {
    if (!("serviceWorker" in navigator)) return;
    try {
      await navigator.serviceWorker.register("/static/browser-codec-sw.js");
    } catch (error) {
      console.warn("Browser codec asset cache worker could not register.", error);
    }
  }

  function ensureClientCodec() {
    if (clientInitialisation) return clientInitialisation;
    clientInitialisation = (async () => {
      try {
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
    window.addEventListener("hashchange", () => { void resolveFragment(); });
    inputLinkElement.addEventListener("input", () => { void updateOutput(); });
    transportSelect.addEventListener("change", () => { void updateOutput(); });
    executionSelect.addEventListener("change", () => {
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
    qrSetting.addEventListener("change", () => { void updateOutput(); });
    qrCodeCorrectionLevelElement.addEventListener("change", () => { void updateOutput(); });
    setVisibleApplication();
    if (await resolveFragment()) return;
    void ensureClientCodec().catch(() => {});
    await updateOutput();
  }

  initialise();
})();
