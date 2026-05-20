// ========== 应用状态 ==========
const state = {
    currentPersona: null,
    history: [],
    isStreaming: false,
    apiKey: localStorage.getItem("anthropic_api_key") || "",
};

// ========== DOM 引用 ==========
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const selectState = $("#select-state");
const chatState = $("#chat-state");
const personaGrid = $("#persona-grid");
const chatMessages = $("#chat-messages");
const chatInput = $("#chat-input");
const sendBtn = $("#send-btn");
const backBtn = $("#back-btn");
const chatAvatar = $("#chat-avatar");
const chatName = $("#chat-name");
const chatTagline = $("#chat-tagline");
const settingsToggle = $("#settings-toggle");
const settingsPanel = $("#settings-panel");
const apiKeyInput = $("#api-key-input");
const saveApiKeyBtn = $("#save-api-key");
const keyPrompt = $("#key-prompt");
const keyPromptInput = $("#key-prompt-input");
const keyPromptSave = $("#key-prompt-save");

// ========== API Key 管理 ==========
function hasApiKey() {
    return !!state.apiKey;
}

function updateKeyUI() {
    const has = hasApiKey();
    // 主页的 key 提示
    if (keyPrompt) {
        keyPrompt.classList.toggle("hidden", has);
    }
    // 设置面板同步
    apiKeyInput.value = state.apiKey;
    // 人格卡片启用/禁用
    $$(".persona-card").forEach(card => {
        card.classList.toggle("disabled", !has);
    });
}

function saveApiKey(key) {
    state.apiKey = key.trim();
    localStorage.setItem("anthropic_api_key", state.apiKey);
    updateKeyUI();
}

// 主页 Key 输入
keyPromptSave.addEventListener("click", () => {
    saveApiKey(keyPromptInput.value);
});

keyPromptInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
        saveApiKey(keyPromptInput.value);
    }
});

// 设置面板
settingsToggle.addEventListener("click", () => {
    settingsPanel.classList.toggle("hidden");
});

saveApiKeyBtn.addEventListener("click", () => {
    saveApiKey(apiKeyInput.value);
    settingsPanel.classList.add("hidden");
});

// 点击其他地方关闭设置
document.addEventListener("click", (e) => {
    if (!e.target.closest("#settings-bar")) {
        settingsPanel.classList.add("hidden");
    }
});

// 初始化
updateKeyUI();

// ========== 人格选择 ==========
personaGrid.addEventListener("click", async (e) => {
    const card = e.target.closest(".persona-card");
    if (!card || card.classList.contains("disabled")) return;

    if (!hasApiKey()) {
        keyPrompt.classList.remove("hidden");
        keyPromptInput.focus();
        return;
    }

    const personaId = card.dataset.id;
    try {
        const resp = await fetch("/api/personas");
        const personas = await resp.json();
        state.currentPersona = personas.find((p) => p.id === personaId);
        if (!state.currentPersona) return;

        // 从后端加载完整人格信息（含 welcome_message）
        const detailResp = await fetch(`/api/personas?detail=true`);
        // welcome_message 在前端用 dataset 传也行，这里简化：通过再次请求
        // 实际上 welcome_message 已通过模板渲染传入 dataset
        const themeColor = card.dataset.theme || "#4fc3f7";

        enterChat(personaId, themeColor);
    } catch (err) {
        console.error("加载人格失败:", err);
    }
});

// ========== 进入聊天 ==========
function enterChat(personaId, themeColor) {
    selectState.classList.add("hidden");
    chatState.classList.remove("hidden");
    chatMessages.innerHTML = "";

    chatAvatar.textContent = state.currentPersona.avatar;
    chatName.textContent = state.currentPersona.name;
    chatTagline.textContent = state.currentPersona.tagline;

    document.documentElement.style.setProperty("--accent", themeColor);

    state.history = [];

    // 直接显示人格的欢迎语，不需要 API 调用
    if (state.currentPersona.welcome_message) {
        createMessage("bot", state.currentPersona.avatar, state.currentPersona.welcome_message);
        state.history.push({
            role: "assistant",
            content: state.currentPersona.welcome_message,
        });
    }

    chatInput.focus();
}

// ========== 返回选择 ==========
backBtn.addEventListener("click", () => {
    chatState.classList.add("hidden");
    selectState.classList.remove("hidden");
    state.currentPersona = null;
    state.history = [];
    state.isStreaming = false;
    sendBtn.disabled = false;
    document.documentElement.style.setProperty("--accent", "#4fc3f7");
});

// ========== 发送消息 ==========
async function sendMessage() {
    const message = chatInput.value.trim();
    if (!message || state.isStreaming || !state.currentPersona || !hasApiKey()) return;

    chatInput.value = "";
    chatInput.style.height = "auto";

    // 显示用户消息
    createMessage("user", "👤", message);
    state.history.push({ role: "user", content: message });

    // 显示打字指示器
    const typingDiv = showTypingIndicator();
    scrollToBottom();

    state.isStreaming = true;
    sendBtn.disabled = true;

    try {
        const resp = await fetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                persona_id: state.currentPersona.id,
                message: message,
                history: state.history.slice(0, -1),
                api_key: state.apiKey,
            }),
        });

        if (!resp.ok) {
            removeTypingIndicator();
            addError("请求失败: HTTP " + resp.status);
            state.isStreaming = false;
            sendBtn.disabled = false;
            return;
        }

        removeTypingIndicator();
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let fullText = "";
        const botDiv = createMessage("bot", state.currentPersona.avatar, "");

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() || "";

            for (const line of lines) {
                if (!line.startsWith("data: ")) continue;
                const data = JSON.parse(line.slice(6));

                if (data.error) {
                    addError(data.error);
                    state.isStreaming = false;
                    sendBtn.disabled = false;
                    return;
                }

                if (data.text) {
                    fullText += data.text;
                    botDiv.querySelector(".message-content").textContent = fullText;
                    scrollToBottom();
                }

                if (data.done) {
                    state.isStreaming = false;
                    sendBtn.disabled = false;
                    state.history.push({ role: "assistant", content: fullText });
                }
            }
        }
    } catch (err) {
        removeTypingIndicator();
        addError("请求失败: " + err.message);
        state.isStreaming = false;
        sendBtn.disabled = false;
    }
}

sendBtn.addEventListener("click", sendMessage);

chatInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

// 自动调整输入框高度
chatInput.addEventListener("input", () => {
    chatInput.style.height = "auto";
    chatInput.style.height = Math.min(chatInput.scrollHeight, 120) + "px";
});

// ========== 辅助函数 ==========
function createMessage(role, avatar, content) {
    const div = document.createElement("div");
    div.className = `message ${role}`;
    div.innerHTML = `
        <div class="message-avatar">${avatar}</div>
        <div class="message-content">${content}</div>
    `;
    chatMessages.appendChild(div);
    return div;
}

function addError(text) {
    const div = document.createElement("div");
    div.className = "error-msg";
    div.textContent = text;
    chatMessages.appendChild(div);
    scrollToBottom();
}

function showTypingIndicator() {
    const div = document.createElement("div");
    div.className = "typing-indicator";
    div.innerHTML = "<span></span><span></span><span></span>";
    chatMessages.appendChild(div);
    return div;
}

function removeTypingIndicator() {
    const indicator = chatMessages.querySelector(".typing-indicator");
    if (indicator) indicator.remove();
}

function scrollToBottom() {
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

// ========== 键盘快捷键 ==========
document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !selectState.classList.contains("hidden")) {
        chatInput.blur();
    }
});
