(() => {
  const inputLinkElement = document.querySelector("#input-link");
  const outputLinkElement = document.querySelector("#output-link");
  const outputRatioElement = document.querySelector("#output-ratio");
  const queryWarningElement = document.querySelector("#query-warning");
  const qrCodeImage = document.querySelector("#qrcode");
  const qrCodeCorrectionLevelContainer = document.querySelector("#qr-correct-level-container");
  const qrCodeCorrectionLevelElement = document.querySelector("#qr-correct-level");
  const transportSelect = document.querySelector("#settings-transport");
  const qrSetting = document.querySelector("#settings-qr");
  const loader = document.querySelector("#loader");
  const content = document.querySelector("#content");

  let updateVersion = 0;

  const api = async (endpoint, body) => {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Request failed");
    return payload;
  };

  const currentBaseLink = () => `${window.location.origin}${window.location.pathname}`;

  function setVisibleApplication () {
    loader.style.opacity = 0;
    content.style.opacity = 1;
    content.style.pointerEvents = "auto";
  }

  function updateQueryWarning (input) {
    try {
      const candidate = input.includes("://") ? input : `http://${input}`;
      const url = new URL(candidate);
      queryWarningElement.style.display = url.searchParams.size > 1 ? "inline" : "none";
    } catch (_) {
      queryWarningElement.style.display = "none";
    }
  }

  async function updateOutput () {
    const version = ++updateVersion;
    const input = inputLinkElement.value.trim();
    if (!input) {
      outputLinkElement.textContent = "Enter a link above to compress";
      outputLinkElement.removeAttribute("href");
      outputLinkElement.style.color = "";
      outputRatioElement.style.color = "rgba(255, 255, 255, 0)";
      queryWarningElement.style.display = "none";
      qrCodeImage.style.display = "none";
      qrCodeCorrectionLevelContainer.style.display = "none";
      return;
    }

    try {
      const mode = transportSelect.value;
      const textOutput = await api("/api/compress", { url: input, mode });
      if (version !== updateVersion) return;

      const normalised = input.replace(/^https?:\/\//, "");
      const ratio = (1 - (Array.from(textOutput.payload).length + window.location.host.length) / Math.max(normalised.length, 1)) * 100;
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

      const link = `${currentBaseLink()}#${textOutput.payload}`;
      outputLinkElement.textContent = link;
      outputLinkElement.href = link;
      outputLinkElement.style.color = "";
      updateQueryWarning(input);

      if (qrSetting.checked) {
        const qrOutput = await api("/api/qr", {
          url: input,
          correction_level: Number(qrCodeCorrectionLevelElement.value)
        });
        if (version !== updateVersion) return;
        qrCodeImage.style.display = "inline";
        qrCodeCorrectionLevelContainer.style.display = "inline";
        qrCodeImage.src = qrOutput.image;
        qrCodeImage.title = qrOutput.link;
      } else {
        qrCodeImage.style.display = "none";
        qrCodeCorrectionLevelContainer.style.display = "none";
      }
    } catch (error) {
      if (version !== updateVersion) return;
      outputLinkElement.textContent = "Invalid link";
      outputLinkElement.style.color = "rgb(255, 50, 50)";
      outputLinkElement.removeAttribute("href");
      outputRatioElement.style.color = "rgba(255, 255, 255, 0)";
      queryWarningElement.style.display = "none";
      qrCodeImage.style.display = "none";
      qrCodeCorrectionLevelContainer.style.display = "none";
      console.error(error);
    }
  }

  function resolveFragment () {
    if (!window.location.hash) return false;
    const payload = decodeURIComponent(window.location.hash.slice(1)).replaceAll(" ", "");
    if (!payload.trim()) return false;
    const resolver = new URL("/resolve", window.location.origin);
    resolver.searchParams.set("payload", payload);
    window.location.replace(resolver);
    return true;
  }

  async function initialise () {
    window.addEventListener("hashchange", () => { resolveFragment(); });
    if (resolveFragment()) return;
    inputLinkElement.addEventListener("input", updateOutput);
    transportSelect.addEventListener("change", updateOutput);
    qrSetting.addEventListener("change", updateOutput);
    qrCodeCorrectionLevelElement.addEventListener("change", updateOutput);
    await updateOutput();
    setVisibleApplication();
  }

  initialise();
})();
