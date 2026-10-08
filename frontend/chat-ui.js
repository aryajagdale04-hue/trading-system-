(function () {
  let busy = false;

  function safeCitationUrl(value) {
    try {
      const url = new URL(value);
      return (url.protocol === "https:" || url.protocol === "http:") && !url.username && !url.password ? url.href : null;
    } catch (_) { return null; }
  }

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function answerText(data) {
    if (typeof data?.answer === "string" && data.answer.trim()) return data.answer.trim();
    // Be defensive if a proxy/provider returns a structured text part instead
    // of the API's documented string. Never let an object become [object Object].
    const answer = data?.answer;
    if (answer && typeof answer === "object") {
      for (const key of ["text", "content", "answer"]) {
        if (typeof answer[key] === "string" && answer[key].trim()) return answer[key].trim();
      }
    }
    return null;
  }

  function readableAnswer(value) {
    return String(value || "")
      .replace(/^[ \t]*#{1,6}[ \t]+/gm, "")
      .replace(/\*\*(.+?)\*\*/g, "$1")
      .replace(/__(.+?)__/g, "$1")
      .replace(/\*(.+?)\*/g, "$1")
      .replace(/_(.+?)_/g, "$1")
      .replace(/^[ \t]*[-*+][ \t]+/gm, "• ")
      .replace(/^[ \t]*---+[ \t]*$/gm, "")
      .trim();
  }

  function normalizeLookupText(value) {
    return String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  }

  async function resolveSymbol(question) {
    // Chat input can be a short company name or ticker. Keep full questions and
    // pasted headlines out of symbol search; they are not symbol identifiers.
    let query = question.trim().replace(/[?!.,]+$/, "");
    query = query.replace(/^(?:tell me about|what about|explain|analyze|analyse|stock)\s+/i, "").trim();
    if (!query || query.length > 80 || query.split(/\s+/).length > 5) return null;
    try {
      const response = await fetch(`/api/symbols?q=${encodeURIComponent(query)}`);
      if (!response.ok) return null;
      const payload = await response.json();
      const results = Array.isArray(payload?.results) ? payload.results : [];
      const normalizedQuery = normalizeLookupText(query);
      const exactSymbol = results.find((item) => typeof item?.symbol === "string" && item.symbol.toLowerCase() === query.toLowerCase());
      if (exactSymbol) return exactSymbol.symbol;
      const exactName = results.filter((item) => normalizeLookupText(item?.name) === normalizedQuery);
      if (exactName.length === 1) return exactName[0].symbol;
      const nameMatches = results.filter((item) => normalizeLookupText(item?.name).startsWith(normalizedQuery));
      return nameMatches.length === 1 ? nameMatches[0].symbol : null;
    } catch (_) { return null; }
  }

  function makeChat(mount, withStock) {
    const history = [];
    const root = element("section", "ai-chat");
    root.setAttribute("aria-label", "AI stock research chat");
    const messages = element("div", "chat-messages");
    messages.setAttribute("aria-live", "polite");
    const starters = element("div", "chat-starters");
    ["Explain this stock in simple words", "Paste a news headline and explain its possible impact", "What does the chart show?"].forEach((label) => {
      const button = element("button", "chat-starter", label); button.type = "button";
      button.addEventListener("click", () => { input.value = label; form.requestSubmit(); });
      starters.append(button);
    });
    const form = element("form", "chat-form");
    const input = element("textarea", "chat-input");
    input.rows = 2; input.maxLength = 2000; input.placeholder = "Ask about a stock, news, or a chart…";
    input.setAttribute("aria-label", "Your question");
    const send = element("button", "chat-send", "Ask"); send.type = "submit";
    form.append(input, send);
    const disclaimer = element("p", "chat-disclaimer", "Learning and research only. This chat cannot tell you whether to buy or sell. Check sources and consider different possible outcomes.");
    root.append(messages, starters, form, disclaimer); mount.replaceChildren(root);

    function render() {
      messages.replaceChildren();
      history.forEach((item) => {
        const bubble = element("article", `chat-message ${item.role}`, item.content);
        messages.append(bubble);
        if (item.sources?.length) {
          const list = element("ul", "chat-sources");
          item.sources.forEach((source) => {
            const href = safeCitationUrl(source.url); if (!href) return;
            const li = element("li"); const a = element("a", "", source.title || "Source");
            a.href = href; a.target = "_blank"; a.rel = "noopener noreferrer"; li.append(a); list.append(li);
          });
          if (list.childNodes.length) messages.append(list);
        }
        if (item.context_as_of) messages.append(element("small", "chat-asof", `Stock data read at ${item.context_as_of} (UTC)`));
      });
      if (busy) messages.append(element("p", "chat-pending", "Looking that up…"));
      messages.scrollTop = messages.scrollHeight;
      send.disabled = busy;
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault(); const question = input.value.trim(); if (!question || busy) return;
      if (!withStock && question === "Explain this stock in simple words" && !window.getStockChatContext?.().symbol) {
        history.push({ role: "user", content: question });
        history.push({ role: "assistant", content: "Tell me the company name or ticker symbol, such as RELIANCE, and I’ll explain it. You can also select a stock using the search box above." });
        input.value = ""; render(); return;
      }
      history.push({ role: "user", content: question }); if (history.length > 32) history.splice(0, history.length - 32);
      input.value = ""; busy = true; render();
      const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 50000);
      try {
        const response = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, signal: controller.signal,
          body: JSON.stringify({ messages: history, ...await (async () => {
            if (withStock && window.getStockChatContext) return window.getStockChatContext();
            const symbol = await resolveSymbol(question);
            return symbol ? { symbol } : {};
          })() }) });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "The chat could not answer. Please try again.");
        const answer = answerText(data);
        if (!answer) throw new Error("The chat returned an unreadable reply. Please try again.");
        history.push({ role: "assistant", content: readableAnswer(answer), sources: Array.isArray(data.sources) ? data.sources : [], context_as_of: data.context_as_of });
      } catch (error) {
        history.push({ role: "assistant", content: error.name === "AbortError" ? "That took too long. Please try again." : error.message || "Chat is temporarily unavailable. Please try again." });
      } finally { clearTimeout(timer); busy = false; render(); }
    });
    render();
  }

  window.StockChat = { safeCitationUrl, answerText, readableAnswer, normalizeLookupText, init() { makeChat(document.getElementById("home-chat-mount"), false); makeChat(document.getElementById("stock-chat-mount"), true); } };
  if (typeof document !== "undefined") {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", window.StockChat.init, { once: true });
    else window.StockChat.init();
  }
})();
