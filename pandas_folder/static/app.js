const form = document.querySelector("#upload-form");
const input = document.querySelector("#photo-input");
const dropzone = document.querySelector("#dropzone");
const dropzoneContent = document.querySelector("#dropzone-content");
const previewWrap = document.querySelector("#preview-wrap");
const preview = document.querySelector("#photo-preview");
const button = document.querySelector("#analyze-button");
const buttonLabel = button.querySelector(".button-label");
const message = document.querySelector("#form-message");
const resultSection = document.querySelector("#result-section");
const resultCard = document.querySelector("#result-card");
const aiStatus = document.querySelector("#ai-status");
const askForm = document.querySelector("#ask-form");
const questionInput = document.querySelector("#question-input");
const askButton = document.querySelector("#ask-button");
const askMessage = document.querySelector("#ask-message");
const answerCard = document.querySelector("#answer-card");
const answerContent = document.querySelector("#answer-content");

const allowedTypes = new Set(["image/jpeg", "image/png", "image/webp"]);
const maxFileSize = 8 * 1024 * 1024;
let selectedFile = null;
let previewUrl = null;

function renderStatus(title, description, isError = false, isLoading = false) {
  resultCard.innerHTML = `
    <div class="result-placeholder${isError ? " result-placeholder--error" : ""}">
      <span class="result-kicker">${isError ? "PLANT CHECK NOT COMPLETED" : "YOUR PLANT CHECK"}</span>
      <h2>${escapeHTML(title)}</h2>
      <p>${escapeHTML(description)}</p>
    </div>
  `;
  resultSection.setAttribute("aria-busy", String(isLoading));
}

fetch("/api/health")
  .then((response) => {
    if (!response.ok) throw new Error("The health check failed.");
    return response.json();
  })
  .then((health) => {
    const providerName = health.ai_provider === "openrouter" ? "OpenRouter" : "Gemini";
    aiStatus.dataset.provider = providerName;
    aiStatus.textContent = health.ai_configured
      ? `${providerName} API key is configured. Free model availability may vary.`
      : `${providerName} needs an API key. See the README to enable plant checks.`;
    aiStatus.classList.toggle("is-ready", health.ai_configured);
  })
  .catch(() => {
    aiStatus.textContent = "Could not reach the analysis service. Check that the backend is running.";
    aiStatus.classList.add("is-error");
  });

function showMessage(text, isLoading = false) {
  message.textContent = text;
  message.classList.toggle("is-loading", isLoading);
}

function resetPreviewUrl() {
  if (previewUrl) {
    URL.revokeObjectURL(previewUrl);
    previewUrl = null;
  }
}

function selectPhoto(file) {
  if (!file) return;
  if (!allowedTypes.has(file.type)) {
    showMessage("Please choose a JPG, PNG, or WEBP image.");
    return;
  }
  if (file.size > maxFileSize) {
    showMessage("That photo is over 8 MB. Choose a smaller image.");
    return;
  }
  if (file.size === 0) {
    showMessage("That photo is empty. Please choose another one.");
    return;
  }

  resetPreviewUrl();
  selectedFile = file;
  previewUrl = URL.createObjectURL(file);
  preview.src = previewUrl;
  previewWrap.hidden = false;
  dropzoneContent.hidden = true;
  button.disabled = false;
  showMessage("");
  renderStatus("Photo ready to check", "Your plant observations and care suggestions will appear here after analysis.");
}

input.addEventListener("change", () => selectPhoto(input.files?.[0]));

dropzone.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    input.click();
  }
});

for (const eventName of ["dragenter", "dragover"]) {
  dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropzone.classList.add("is-dragging");
  });
}

for (const eventName of ["dragleave", "drop"]) {
  dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropzone.classList.remove("is-dragging");
  });
}

dropzone.addEventListener("drop", (event) => {
  selectPhoto(event.dataTransfer?.files?.[0]);
});

function escapeHTML(value) {
  return String(value).replace(/[&<>"']/g, (character) => {
    const entities = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    };
    return entities[character];
  });
}

askForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = questionInput.value.trim();
  if (question.length < 3) {
    askMessage.textContent = "Please enter a little more detail.";
    askMessage.classList.add("is-error");
    return;
  }

  askButton.disabled = true;
  askButton.classList.add("is-loading");
  askButton.querySelector(".button-label").textContent = "Thinking";
  askMessage.textContent = "Leafwise is preparing an answer…";
  askMessage.classList.remove("is-error");
  answerCard.hidden = true;

  try {
    const response = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "We couldn't answer that question. Please try again.");
    answerContent.textContent = result.answer;
    answerCard.hidden = false;
    askMessage.textContent = "AI answers are a starting point; check advice against your plant and local conditions.";
  } catch (error) {
    askMessage.textContent = error instanceof Error ? error.message : "Something went wrong. Please try again.";
    askMessage.classList.add("is-error");
  } finally {
    askButton.disabled = false;
    askButton.classList.remove("is-loading");
    askButton.querySelector(".button-label").textContent = "Ask Leafwise";
  }
});

function renderList(items) {
  if (!Array.isArray(items) || items.length === 0) {
    return "<li>No clear signs noted.</li>";
  }
  return items.map((item) => `<li>${escapeHTML(item)}</li>`).join("");
}

function renderResult(analysis) {
  const declineEstimate =
    Number.isInteger(analysis.estimated_days_to_severe_decline) &&
    analysis.estimated_days_to_severe_decline > 0
      ? `A rough estimate: severe decline may happen within about ${analysis.estimated_days_to_severe_decline} days. This is highly uncertain.`
      : "A plant's remaining lifespan cannot be reliably estimated from a single photo.";

  resultCard.innerHTML = `
    <div class="result-topline">
      <div>
        <span class="result-kicker">YOUR PLANT CHECK</span>
        <h2>${escapeHTML(analysis.plant_name || "Plant check")}</h2>
        <p>${escapeHTML(analysis.condition || "")}</p>
      </div>
      <span class="confidence">${escapeHTML(analysis.confidence)}% confidence</span>
    </div>
    <div class="result-columns">
      <section>
        <h3>What we noticed</h3>
        <p>${escapeHTML(analysis.disease || "No clear disease identified")}</p>
        <ul>${renderList(analysis.symptoms)}</ul>
      </section>
      <section>
        <h3>Care &amp; treatment</h3>
        <ul>${renderList(analysis.treatment)}</ul>
      </section>
      <section>
        <h3>How to prevent it</h3>
        <ul>${renderList(analysis.prevention)}</ul>
      </section>
      <section>
        <h3>Plant outlook</h3>
        <p>${escapeHTML(analysis.survival_outlook || "The outlook is uncertain from one photo.")}</p>
        <p class="decline-estimate">${escapeHTML(declineEstimate)}</p>
      </section>
    </div>
    <p class="result-disclaimer">AI photo checks can be wrong and cannot predict an exact death date. Monitor the plant and consult a local agricultural expert if it is worsening.</p>
  `;
  resultSection.setAttribute("aria-busy", "false");
  resultSection.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!selectedFile || button.disabled) return;

  const formData = new FormData();
  formData.append("photo", selectedFile);
  button.disabled = true;
  button.classList.add("is-loading");
  buttonLabel.textContent = "Taking a closer look";
  showMessage("Sending your photo securely for a health check…", true);
  renderStatus("Checking your plant…", `${aiStatus.dataset.provider || "The AI model"} is analyzing the photo. Your results will appear here.`, false, true);
  resultSection.scrollIntoView({ behavior: "smooth", block: "nearest" });

  try {
    const response = await fetch("/api/analyze", {
      method: "POST",
      body: formData,
    });
    let result;
    try {
      result = await response.json();
    } catch {
      throw new Error("The analysis service returned an unreadable response. Please try again.");
    }
    if (!response.ok) {
      throw new Error(result.detail || "We couldn't check that photo. Please try again.");
    }
    renderResult(result);
    showMessage("");
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : "Something went wrong. Please try again.";
    showMessage(errorMessage);
    renderStatus("We couldn't complete the plant check", errorMessage, true);
    resultSection.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } finally {
    button.disabled = !selectedFile;
    button.classList.remove("is-loading");
    buttonLabel.textContent = "Check my plant";
  }
});

window.addEventListener("beforeunload", resetPreviewUrl);
