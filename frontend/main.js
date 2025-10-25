class HttpError extends Error {
  constructor(message, status, data) {
    super(message);
    this.name = "HttpError";
    this.status = status;
    this.data = data;
  }
}

const formsByTask = {
  email: document.getElementById("emailForm"),
  search: document.getElementById("searchForm"),
  pizza: document.getElementById("pizzaForm"),
  pdf: document.getElementById("pdfForm"),
};

const toggleButtons = Array.from(document.querySelectorAll(".task-toggle"));
const cancelButtons = Array.from(document.querySelectorAll(".cancel-task"));
const logContainer = document.getElementById("log");
const logTemplate = document.getElementById("logEntryTemplate");
const outputContent = document.getElementById("outputContent");
const conversationStream = document.getElementById("conversationStream");
const conversationTemplate = document.getElementById("conversationMessageTemplate");
const localStatusIndicator = document.getElementById("localStatus");

const ACTION_TITLES = {
  send_email: "Email",
  schedule_meeting: "Meeting",
  search_web: "Web Search",
  order_pizza: "Pizza Order",
  pdf_question: "PDF Answer",
  answer_question: "Answer",
};
const promptInput = document.getElementById("promptInput");
const sendPromptButton = document.getElementById("sendPrompt");

let activeTask = null;

const LOCAL_STATUS_CLASSES = [
  "status-available",
  "status-unavailable",
  "status-error",
  "status-unknown",
];

function setLocalStatusIndicator(state) {
  if (!localStatusIndicator) {
    return;
  }

  localStatusIndicator.classList.remove(...LOCAL_STATUS_CLASSES);

  if (!state) {
    localStatusIndicator.classList.add("status-unknown");
    localStatusIndicator.textContent = "Local model status: unavailable (unknown).";
    return;
  }

  const { available, provider, model, message } = state;
  if (available) {
    localStatusIndicator.classList.add("status-available");
    const providerLabel = provider || "local";
    const modelLabel = model && model !== "<uninitialised>" ? model : "model";
    localStatusIndicator.textContent = `Local model status: online (${providerLabel} · ${modelLabel}).`;
  } else {
    localStatusIndicator.classList.add("status-unavailable");
    const reason = message || "Local runtime is not responding.";
    localStatusIndicator.textContent = `Local model status: offline — ${reason}`;
  }
}

async function refreshLocalStatus() {
  if (!localStatusIndicator) {
    return;
  }

  try {
    const response = await fetch("/status/local_model", { cache: "no-store" });
    if (!response.ok) {
      throw new HttpError("Unable to check local model status.", response.status);
    }
    const data = await response.json();
    setLocalStatusIndicator(data);
  } catch (error) {
    localStatusIndicator.classList.remove(...LOCAL_STATUS_CLASSES);
    localStatusIndicator.classList.add("status-error");
    const message =
      error instanceof HttpError
        ? error.message || "Unable to reach the server."
        : "Unable to reach the server.";
    localStatusIndicator.textContent = `Local model status: error — ${message}`;
  }
}

function toggleTask(taskId) {
  if (!taskId || !formsByTask[taskId]) {
    return;
  }

  if (activeTask === taskId) {
    hideActiveTask();
    return;
  }

  activeTask = taskId;
  Object.entries(formsByTask).forEach(([key, form]) => {
    form.classList.toggle("hidden", key !== taskId);
  });

  toggleButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.task === taskId);
  });
}

function hideActiveTask() {
  Object.values(formsByTask).forEach((form) => form.classList.add("hidden"));
  toggleButtons.forEach((button) => button.classList.remove("active"));
  activeTask = null;
}

function setBusy(element, isBusy, label) {
  if (!element) return;
  if (isBusy) {
    element.dataset.originalText = element.textContent;
    element.textContent = label || "Working…";
    element.disabled = true;
  } else {
    element.textContent = element.dataset.originalText ?? element.textContent;
    element.disabled = false;
  }
}

function formatPayload(payload) {
  if (payload === null || payload === undefined) {
    return "";
  }
  if (typeof payload === "string") {
    return payload;
  }

  if (typeof payload === "object") {
    if ("answer" in payload && typeof payload.answer === "string" && Object.keys(payload).length === 1) {
      return payload.answer;
    }
    if ("result" in payload && typeof payload.result === "string") {
      return payload.result;
    }
  }

  if (typeof payload === "string") {
    return payload;
  }
  try {
    return JSON.stringify(payload, null, 2);
  } catch (err) {
    return String(payload);
  }
}

function isDomNode(value) {
  return value && typeof value === "object" && typeof value.nodeType === "number";
}

function createClarificationsList(clarifications) {
  const wrapper = document.createElement("div");
  wrapper.className = "clarification-list";

  clarifications.forEach((item) => {
    if (!item || typeof item !== "object") {
      return;
    }
    const block = document.createElement("article");
    block.className = "clarification-item";

    const heading = document.createElement("h4");
    const promptText =
      (typeof item.prompt === "string" && item.prompt) ||
      (item.field ? `Please provide ${item.field}.` : "Please provide the missing details.");
    heading.textContent = promptText;
    block.appendChild(heading);

    const metaParts = [];
    if (item.action) {
      metaParts.push(`Action: ${ACTION_TITLES[item.action] || item.action}`);
    }
    if (item.field) {
      metaParts.push(`Field: ${item.field}`);
    }
    if (metaParts.length) {
      const meta = document.createElement("p");
      meta.textContent = metaParts.join(" • ");
      block.appendChild(meta);
    }

    if (item.payload) {
      const code = document.createElement("code");
      code.textContent =
        typeof item.payload === "string" ? item.payload : JSON.stringify(item.payload, null, 2);
      block.appendChild(code);
    }

    wrapper.appendChild(block);
  });

  if (!wrapper.childElementCount) {
    const fallback = document.createElement("p");
    fallback.textContent = "Assistant requested additional information.";
    wrapper.appendChild(fallback);
  }

  return wrapper;
}

function appendConversationMessage(speaker, content, options = {}) {
  if (!conversationStream || !conversationTemplate) {
    return;
  }

  const { tone = "assistant" } = options;
  const entry = conversationTemplate.content.firstElementChild.cloneNode(true);
  entry.classList.add(`speaker-${tone}`);

  const metaSpeaker = entry.querySelector(".conversation-speaker");
  const metaTime = entry.querySelector(".conversation-time");
  const body = entry.querySelector(".conversation-body");

  metaSpeaker.textContent = speaker;
  metaTime.textContent = new Date().toLocaleTimeString();

  const appendValue = (value) => {
    if (value === undefined || value === null) {
      return;
    }
    if (isDomNode(value)) {
      body.appendChild(value);
      return;
    }
    if (typeof value === "string") {
      const paragraph = document.createElement("p");
      paragraph.textContent = value;
      body.appendChild(paragraph);
      return;
    }
    const pre = document.createElement("pre");
    pre.className = "output-data";
    pre.textContent = formatPayload(value);
    body.appendChild(pre);
  };

  if (Array.isArray(content)) {
    content.forEach(appendValue);
  } else {
    appendValue(content);
  }

  conversationStream.classList.remove("empty");
  const placeholder = conversationStream.querySelector(".placeholder");
  if (placeholder) {
    placeholder.remove();
  }

  conversationStream.appendChild(entry);
  while (conversationStream.childElementCount > 50) {
    conversationStream.firstElementChild?.remove();
  }
  conversationStream.scrollTop = conversationStream.scrollHeight;
}

function summariseAssistantResponse(payload) {
  if (payload === null || payload === undefined) {
    return "All set.";
  }
  if (typeof payload === "string") {
    return payload;
  }
  if (typeof payload.detail === "string") {
    return payload.detail;
  }
  if (Array.isArray(payload.clarifications) && payload.clarifications.length) {
    const lines = ["I need a bit more information before I can continue:"];
    payload.clarifications.forEach((item, index) => {
      const promptText =
        (item && typeof item.prompt === "string" && item.prompt) ||
        (item && item.field ? `Provide ${item.field}.` : "Please share the missing detail.");
      lines.push(`${index + 1}. ${promptText}`);
    });
    return lines.join("\n");
  }
  if (typeof payload.answer === "string") {
    return payload.answer;
  }
  if (Array.isArray(payload.actions) && payload.actions.length) {
    const lines = payload.actions.map((item) => {
      const title = ACTION_TITLES[item.action] || item.action || "Action";
      const result = item.result;
      if (result && typeof result === "object") {
        if (typeof result.answer === "string") {
          return `${title}: ${result.answer}`;
        }
        if (typeof result.status === "string") {
          return `${title}: ${result.status}`;
        }
      }
      if (typeof result === "string") {
        return `${title}: ${result}`;
      }
      return `${title} completed.`;
    });
    return lines.join("\n");
  }
  return formatPayload(payload);
}

function appendLog(type, payload, options = {}) {
  const { error = false } = options;
  const entry = logTemplate.content.firstElementChild.cloneNode(true);
  const metaType = entry.querySelector(".log-type");
  const metaTime = entry.querySelector(".log-time");
  const content = entry.querySelector(".log-content");

  entry.classList.toggle("error", error);
  metaType.textContent = error ? `${type} ⚠️` : type;
  metaTime.textContent = new Date().toLocaleTimeString();
  content.textContent = formatPayload(payload);

  logContainer.prepend(entry);

  // Keep the log manageable.
  while (logContainer.childElementCount > 40) {
    logContainer.lastElementChild?.remove();
  }
}

function createPreBlock(text) {
  const pre = document.createElement("pre");
  pre.className = "output-data";
  pre.textContent = text;
  return pre;
}

function renderResultsList(results, query) {
  const wrapper = document.createElement("div");
  wrapper.className = "output-results";

  if (query) {
    const queryEl = document.createElement("p");
    queryEl.className = "output-query";
    queryEl.textContent = `Query: ${query}`;
    wrapper.appendChild(queryEl);
  }

  const list = document.createElement("ol");
  list.className = "output-results-list";

  results.forEach((item, idx) => {
    if (!item) {
      return;
    }
    const li = document.createElement("li");
    li.className = "output-results-item";
    li.dataset.index = String(idx + 1);

    if (item.title) {
      const title = document.createElement("h4");
      title.className = "output-result-title";
      title.textContent = item.title;
      li.appendChild(title);
    }

    if (item.link) {
      const link = document.createElement("a");
      link.className = "output-result-link";
      link.href = item.link;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = item.link;
      li.appendChild(link);
    }

    if (item.snippet) {
      const snippet = document.createElement("p");
      snippet.className = "output-result-snippet";
      snippet.textContent = item.snippet;
      li.appendChild(snippet);
    }

    list.appendChild(li);
  });

  wrapper.appendChild(list);
  return wrapper;
}

function renderDataNodes(data) {
  if (data === null || data === undefined) {
    return [createPreBlock("(no data)")];
  }

  if (typeof data === "string") {
    return [createPreBlock(data)];
  }

  if (Array.isArray(data)) {
    if (!data.length) {
      return [createPreBlock("(empty list)")];
    }
    const list = document.createElement("ol");
    list.className = "output-generic-list";
    data.forEach((item) => {
      const li = document.createElement("li");
      li.textContent = typeof item === "string" ? item : JSON.stringify(item, null, 2);
      list.appendChild(li);
    });
    return [list];
  }

  if (typeof data === "object") {
    if (Array.isArray(data.results)) {
      return [renderResultsList(data.results, data.query || data.search || "")];
    }

    if (typeof data.answer === "string" && Object.keys(data).length <= 2) {
      return [createPreBlock(data.answer)];
    }

    return [createPreBlock(JSON.stringify(data, null, 2))];
  }

  return [createPreBlock(String(data))];
}

function buildActionSection(item) {
  const actionKey = item && typeof item === "object" ? item.action : undefined;
  const title = ACTION_TITLES[actionKey] || actionKey || "Response";
  const data = item && typeof item === "object" && "result" in item
    ? item.result
    : item;
  return {
    title,
    nodes: renderDataNodes(data),
  };
}

function buildOutputSections(type, payload) {
  const sections = [];
  const clarifications = Array.isArray(payload?.clarifications) ? payload.clarifications : [];

  let workingPayload = payload;
  if (payload && typeof payload === "object" && !Array.isArray(payload)) {
    workingPayload = { ...payload };
    delete workingPayload.clarifications;
  }

  if (clarifications.length) {
    sections.push({
      title: "Assistant Needs Info",
      nodes: [createClarificationsList(clarifications)],
    });
  }

  const addDefaultSection = (value) => {
    sections.push({
      title: type,
      nodes: renderDataNodes(value),
    });
  };

  if (workingPayload === null || workingPayload === undefined) {
    addDefaultSection(null);
    return sections;
  }

  if (typeof workingPayload === "string") {
    addDefaultSection(workingPayload);
    return sections;
  }

  if (Array.isArray(workingPayload)) {
    addDefaultSection(workingPayload);
    return sections;
  }

  if (typeof workingPayload === "object") {
    if (
      workingPayload.detail &&
      typeof workingPayload.detail === "string" &&
      Object.keys(workingPayload).length <= 2
    ) {
      addDefaultSection(workingPayload.detail);
      return sections;
    }

    if (Array.isArray(workingPayload.actions)) {
      const actionSections = workingPayload.actions
        .filter((item) => item && typeof item === "object")
        .map((item) => buildActionSection(item));
      if (actionSections.length) {
        sections.push(...actionSections);
        return sections;
      }
      addDefaultSection(workingPayload);
      return sections;
    }

    if (workingPayload.action && workingPayload.result !== undefined) {
      sections.push(buildActionSection(workingPayload));
      return sections;
    }

    if (workingPayload.results && Array.isArray(workingPayload.results)) {
      sections.push({
        title: ACTION_TITLES.search_web || type,
        nodes: renderDataNodes(workingPayload),
      });
      return sections;
    }

    if (workingPayload.answer) {
      sections.push({
        title: ACTION_TITLES.answer_question || type,
        nodes: renderDataNodes(workingPayload.answer),
      });
      return sections;
    }

    if (!Object.keys(workingPayload).length && clarifications.length) {
      return sections;
    }
  }

  addDefaultSection(workingPayload);
  return sections;
}

function updateOutputPanel(type, payload, options = {}) {
  if (!outputContent) return;

  const { error = false } = options;
  outputContent.classList.remove("empty");
  outputContent.innerHTML = "";

  if (error) {
    outputContent.classList.add("error");
  } else {
    outputContent.classList.remove("error");
  }

  const header = document.createElement("div");
  header.className = "output-header";

  const title = document.createElement("span");
  title.className = "output-title";
  title.textContent = error ? `${type} ⚠️` : type;
  header.appendChild(title);

  const timestamp = document.createElement("time");
  timestamp.className = "output-timestamp";
  const now = new Date();
  timestamp.dateTime = now.toISOString();
  timestamp.textContent = now.toLocaleTimeString();
  header.appendChild(timestamp);

  outputContent.appendChild(header);

  const body = document.createElement("div");
  body.className = "output-body";

  const sections = buildOutputSections(type, payload);
  sections.forEach((section) => {
    const sectionEl = document.createElement("section");
    sectionEl.className = "output-section";

    if (section.title) {
      const heading = document.createElement("h3");
      heading.className = "output-section-title";
      heading.textContent = section.title;
      sectionEl.appendChild(heading);
    }

    section.nodes.forEach((node) => {
      sectionEl.appendChild(node);
    });

    body.appendChild(sectionEl);
  });

  outputContent.appendChild(body);
}

async function postJSON(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  const text = await response.text();
  let data;

  if (text) {
    try {
      data = JSON.parse(text);
    } catch (err) {
      data = { raw: text };
    }
  }

  if (!response.ok) {
    const message =
      (data && (data.detail || data.error || data.message)) ||
      `${response.status} ${response.statusText}`;
    throw new HttpError(message, response.status, data);
  }

  return data;
}

function pruneEmpty(value) {
  if (Array.isArray(value)) {
    return value
      .map(pruneEmpty)
      .filter((item) => item !== undefined && item !== null);
  }

  if (value && typeof value === "object") {
    const result = {};
    Object.entries(value).forEach(([key, val]) => {
      const cleaned = pruneEmpty(val);
      if (
        cleaned !== undefined &&
        cleaned !== null &&
        !(typeof cleaned === "string" && cleaned.trim() === "")
      ) {
        result[key] = cleaned;
      }
    });
    return Object.keys(result).length ? result : undefined;
  }

  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed.length ? trimmed : undefined;
  }

  return value;
}

async function handleAssistantPrompt() {
  const promptText = promptInput.value.trim();
  if (!promptText) {
    appendLog("Assistant", "Please provide a prompt before sending.", { error: true });
    promptInput.focus();
    return;
  }

  appendConversationMessage("You", promptText, { tone: "user" });
  setBusy(sendPromptButton, true, "Sending…");
  try {
    const data = await postJSON("/assistant/command", { prompt: promptText });
    appendLog("Assistant", data);
    updateOutputPanel("Assistant", data);
    if (Array.isArray(data?.clarifications) && data.clarifications.length) {
      appendConversationMessage("Assistant", [
        "I need a bit more information before moving forward:",
        createClarificationsList(data.clarifications),
      ]);
    } else {
      appendConversationMessage("Assistant", summariseAssistantResponse(data));
    }
  } catch (error) {
    const details = error instanceof HttpError ? error.data || error.message : error;
    appendLog("Assistant Error", details, { error: true });
    updateOutputPanel("Assistant Error", details, { error: true });
    const message =
      error instanceof HttpError
        ? (error.data && (error.data.detail || error.data.error)) || error.message
        : String(details);
    appendConversationMessage("Assistant", message);
  } finally {
    setBusy(sendPromptButton, false);
    await refreshLocalStatus();
  }
}

async function handleEmailSubmit(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button[type='submit']");
  const formData = new FormData(form);

  const payload = {
    to: formData.get("to"),
    subject: formData.get("subject"),
    body: formData.get("body"),
  };

  setBusy(button, true, "Sending…");
  try {
    const data = await postJSON("/email", payload);
    appendLog("Email", data || { status: "sent" });
    updateOutputPanel("Email", data || { status: "sent" });
    form.reset();
    hideActiveTask();
  } catch (error) {
    const details = error instanceof HttpError ? error.data || error.message : error;
    appendLog("Email Error", details, { error: true });
    updateOutputPanel("Email Error", details, { error: true });
  } finally {
    setBusy(button, false);
  }
}

async function handleSearchSubmit(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button[type='submit']");
  const formData = new FormData(form);

  const payload = {
    query: formData.get("query"),
    num_results: Number(formData.get("num_results") || 5),
  };

  setBusy(button, true, "Searching…");
  try {
    const data = await postJSON("/search", payload);
    appendLog("Web Search", data);
    updateOutputPanel("Web Search", data);
    hideActiveTask();
    form.reset();
  } catch (error) {
    const details = error instanceof HttpError ? error.data || error.message : error;
    appendLog("Search Error", details, { error: true });
    updateOutputPanel("Search Error", details, { error: true });
  } finally {
    setBusy(button, false);
  }
}

async function handlePizzaSubmit(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button[type='submit']");
  const formData = new FormData(form);

  const payload = pruneEmpty({
    customer: {
      first_name: formData.get("customer_first_name"),
      last_name: formData.get("customer_last_name"),
      email: formData.get("customer_email"),
      phone: formData.get("customer_phone"),
    },
    address: {
      street: formData.get("address_street"),
      city: formData.get("address_city"),
      region: formData.get("address_region"),
      postal_code: formData.get("address_postal_code"),
    },
    items: [
      {
        code: formData.get("item_code"),
        quantity: Number(formData.get("item_quantity") || 1),
      },
    ],
    special_instructions: formData.get("special_instructions"),
    payment: pruneEmpty({
      card_number: formData.get("payment_card_number"),
      card_expiration: formData.get("payment_card_expiration"),
      card_cvv: formData.get("payment_card_cvv"),
      billing_postal_code: formData.get("payment_billing_postal_code"),
    }),
  });

  setBusy(button, true, "Placing…");
  try {
    const data = await postJSON("/pizza/order", payload);
    appendLog("Pizza Order", data);
    updateOutputPanel("Pizza Order", data);
    hideActiveTask();
    form.reset();
  } catch (error) {
    const details = error instanceof HttpError ? error.data || error.message : error;
    appendLog("Pizza Error", details, { error: true });
    updateOutputPanel("Pizza Error", details, { error: true });
  } finally {
    setBusy(button, false);
  }
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result !== "string") {
        reject(new Error("Unable to read file data."));
        return;
      }
      const [, base64 = ""] = reader.result.split(",");
      resolve(base64);
    };
    reader.onerror = () => reject(reader.error || new Error("File read error."));
    reader.readAsDataURL(file);
  });
}

async function handlePdfSubmit(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button[type='submit']");
  const formData = new FormData(form);
  const files = formData
    .getAll("pdf")
    .filter((item) => item instanceof File);

  if (!files.length) {
    appendLog("PDF Error", "Please choose at least one PDF file.", { error: true });
    updateOutputPanel("PDF Error", "Please choose at least one PDF file.", { error: true });
    return;
  }

  const question = String(formData.get("question") || "").trim();
  if (!question) {
    appendLog("PDF Error", "Please enter a question.", { error: true });
    updateOutputPanel("PDF Error", "Please enter a question.", { error: true });
    return;
  }

  setBusy(button, true, "Asking…");
  try {
    const documents = [];
    for (const file of files) {
      const base64 = await fileToBase64(file);
      documents.push({
        name: file.name,
        data: base64,
      });
    }

    const payload = {
      question,
      documents,
    };

    const data = await postJSON("/assistant/pdf_question", payload);
    appendLog("PDF Answer", data);
    updateOutputPanel("PDF Answer", data);
    hideActiveTask();
    form.reset();
  } catch (error) {
    const details = error instanceof HttpError ? error.data || error.message : error;
    appendLog("PDF Error", details, { error: true });
    updateOutputPanel("PDF Error", details, { error: true });
  } finally {
    setBusy(button, false);
    await refreshLocalStatus();
  }
}

function registerEventListeners() {
  sendPromptButton.addEventListener("click", handleAssistantPrompt);

  promptInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      handleAssistantPrompt();
    }
  });

  toggleButtons.forEach((button) => {
    button.addEventListener("click", () => toggleTask(button.dataset.task));
  });

  cancelButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const target = button.dataset.target;
      if (target && formsByTask[target.replace("Form", "")]) {
        const task = target.replace("Form", "");
        if (formsByTask[task]) {
          formsByTask[task].reset();
        }
      }
      hideActiveTask();
    });
  });

  formsByTask.email.addEventListener("submit", handleEmailSubmit);
  formsByTask.search.addEventListener("submit", handleSearchSubmit);
  formsByTask.pizza.addEventListener("submit", handlePizzaSubmit);
  formsByTask.pdf.addEventListener("submit", handlePdfSubmit);
}

registerEventListeners();
refreshLocalStatus();
setInterval(refreshLocalStatus, 30000);
