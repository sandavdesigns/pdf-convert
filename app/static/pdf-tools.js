function responseFilename(response, fallback) {
  const disposition = response.headers.get("Content-Disposition") || "";
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  const plain = disposition.match(/filename="?([^";]+)"?/i);
  return encoded ? decodeURIComponent(encoded[1]) : (plain ? plain[1] : fallback);
}

function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 60000);
}

document.querySelectorAll(".download-form").forEach((form) => {
  const error = form.querySelector(".form-message");
  const progress = form.querySelector(".form-progress");
  const submit = form.querySelector('button[type="submit"]');
  const fileInput = form.querySelector('input[type="file"]');
  const dropzone = form.querySelector(".dropzone");

  fileInput.addEventListener("change", () => {
    const label = dropzone.querySelector("strong");
    if (fileInput.files.length) label.textContent = fileInput.files[0].name;
  });

  ["dragenter", "dragover"].forEach((eventName) => {
    dropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropzone.classList.add("dragging");
    });
  });
  dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragging"));
  dropzone.addEventListener("drop", (event) => {
    event.preventDefault();
    dropzone.classList.remove("dragging");
    if (event.dataTransfer.files.length) {
      fileInput.files = event.dataTransfer.files;
      fileInput.dispatchEvent(new Event("change"));
    }
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    error.hidden = true;
    progress.hidden = false;
    submit.disabled = true;
    try {
      const response = await fetch(form.action, { method: "POST", body: new FormData(form) });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.error || "Die PDF konnte nicht verarbeitet werden.");
      }
      const blob = await response.blob();
      saveBlob(blob, responseFilename(response, "ergebnis.pdf"));
      const message = document.createElement("div");
      message.className = "message success transient-success";
      message.textContent = form.dataset.success;
      form.insertBefore(message, progress);
      window.setTimeout(() => message.remove(), 8000);
    } catch (exception) {
      error.textContent = exception.message;
      error.hidden = false;
    } finally {
      progress.hidden = true;
      submit.disabled = false;
    }
  });
});

document.querySelectorAll("[data-mode-select]").forEach((select) => {
  const intervalField = select.closest("form").querySelector(".interval-field");
  const intervalInput = intervalField.querySelector("input");
  const updateInterval = () => {
    const visible = select.value === "interval";
    intervalField.hidden = !visible;
    intervalInput.disabled = !visible;
  };
  select.addEventListener("change", updateInterval);
  updateInterval();
});
