// API 端點設定
const API_BASE_URL = 'http://localhost:5000';  // 本地後端 API 位址
const ERROR_MESSAGES = {
    NETWORK_ERROR: '網路回應不正確',
    GENERAL_ERROR: '抱歉，發生了一些錯誤，請稍後再試。'
};

// 防抖函數
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

async function sendMessage(message) {
    try {
        const response = await fetch(`${API_BASE_URL}/chat`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ message: message })
        });

        if (!response.ok) {
            throw new Error(ERROR_MESSAGES.NETWORK_ERROR);
        }

        const data = await response.json();
        return {
            message: data.response
        };
    } catch (error) {
        console.error('發送訊息時發生錯誤:', error);
        return {
            error: true,
            message: ERROR_MESSAGES.GENERAL_ERROR
        };
    }
}

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    const chatContainer = document.getElementById('chat-container');
    const userInput = document.getElementById('user-input');
    const sendButton = document.getElementById('send-button');
    const messageCache = new Map(); // 用於快取已處理的 Markdown

    // 初始化 marked，只需執行一次
    marked.setOptions({
        gfm: true,
        breaks: true,
        headerIds: false,
        mangle: false,
        sanitize: false
    });

    let typingIndicator = null;

    const createTypingIndicator = () => {
        if (typingIndicator) return typingIndicator;
        
        const indicator = document.createElement('div');
        indicator.id = 'typing-indicator';
        indicator.className = 'typing-indicator';
        
        const fragment = document.createDocumentFragment();
        for (let i = 0; i < 3; i++) {
            fragment.appendChild(document.createElement('span'));
        }
        indicator.appendChild(fragment);
        
        return indicator;
    };

    const showTypingIndicator = () => {
        if (!typingIndicator) {
            typingIndicator = createTypingIndicator();
        }
        chatContainer.appendChild(typingIndicator);
        requestAnimationFrame(scrollToBottom);
    };

    const hideTypingIndicator = () => {
        if (typingIndicator?.parentNode) {
            typingIndicator.remove();
            typingIndicator = null;
        }
    };

    const createMessageElement = (message, isUser = false) => {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${isUser ? 'user-message' : 'bot-message'}`;
        
        if (!isUser) {
            // 檢查快取中是否已有處理過的內容
            if (!messageCache.has(message)) {
                const sanitizedHtml = DOMPurify.sanitize(marked.parse(message));
                messageCache.set(message, sanitizedHtml);
            }
            messageDiv.innerHTML = messageCache.get(message);
        } else {
            messageDiv.textContent = message;
        }
        
        return messageDiv;
    };

    const scrollToBottom = () => {
        requestAnimationFrame(() => {
            chatContainer.scrollTop = chatContainer.scrollHeight;
        });
    };

    const handleSubmit = async () => {
        const message = userInput.value.trim();
        if (!message) return;

        // 禁用輸入和按鈕
        userInput.disabled = true;
        sendButton.disabled = true;

        // 清空輸入框並保持焦點
        userInput.value = '';

        try {
            // 使用 DocumentFragment 優化 DOM 操作
            const fragment = document.createDocumentFragment();
            
            // 顯示用戶訊息
            fragment.appendChild(createMessageElement(message, true));
            chatContainer.appendChild(fragment);
            scrollToBottom();

            // 顯示打字指示器
            showTypingIndicator();

            // 發送訊息到後端
            const response = await sendMessage(message);
            
            // 隱藏打字指示器
            hideTypingIndicator();

            // 顯示回應
            fragment.appendChild(createMessageElement(response.message || response.error));
            chatContainer.appendChild(fragment);
            scrollToBottom();
        } catch (error) {
            console.error('處理訊息時發生錯誤:', error);
            hideTypingIndicator();
            chatContainer.appendChild(createMessageElement(ERROR_MESSAGES.GENERAL_ERROR));
            scrollToBottom();
        } finally {
            // 重新啟用輸入和按鈕
            userInput.disabled = false;
            sendButton.disabled = false;
            userInput.focus();
        }
    };

    // 事件監聽
    sendButton.addEventListener('click', handleSubmit);
    userInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSubmit();
        }
    });

    // 使用防抖處理輸入事件
    const debouncedInputHandler = debounce(() => {
        sendButton.disabled = !userInput.value.trim();
    }, 100);

    userInput.addEventListener('input', debouncedInputHandler);

    // 添加歡迎訊息
    const welcomeMessageElement = createMessageElement('您好！我是 AI 客服助理，很高興為您服務。請問有什麼我可以協助您的嗎？');
    chatContainer.appendChild(welcomeMessageElement);
    scrollToBottom();

    // 自動聚焦輸入框
    userInput.focus();
});
