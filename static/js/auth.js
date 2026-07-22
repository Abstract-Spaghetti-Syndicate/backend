async function checkAuthStatus() {
    try {
        const response = await fetch("/api/auth/status");
        const data = await response.json();
        isSystemRegistered = data.is_registered;

        const titleEl = document.getElementById("auth-title");
        const subtitleEl = document.getElementById("auth-subtitle");
        const btnEl = document.getElementById("auth-btn");

        if (isSystemRegistered) {
            titleEl.innerText = "Авторизація";
            subtitleEl.innerText = "Увійдіть, щоб отримати доступ до принтера";
            btnEl.innerText = "Увійти";
        } else {
            titleEl.innerText = "Первинне налаштування";
            subtitleEl.innerText = "Створіть акаунт адміністратора системи";
            btnEl.innerText = "Зареєструватися";
        }

        const token = localStorage.getItem("session_token");
        if (token) {
            showMainPanel();
        }
    } catch (e) {
        console.error("Помилка ініціалізації авторизації:", e);
    }
}

async function handleAuth(event) {
    event.preventDefault();
    const email = document.getElementById("auth-email").value;
    const password = document.getElementById("auth-password").value;

    const endpoint = isSystemRegistered ? "/api/auth/login" : "/api/auth/register";

    try {
        const response = await fetch(endpoint, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({email, password})
        });

        if (!response.ok) {
            const err = await response.json();
            alert("Помилка: " + (err.detail || "Невідома помилка"));
            return;
        }

        const data = await response.json();
        if (data.status === "success" && data.token) {
            localStorage.setItem("session_token", data.token);
            showMainPanel();
        }
    } catch (e) {
        alert("Помилка з'єднання з сервером.");
    }
}

function handleLogout() {
    localStorage.removeItem("session_token");
    if (pollingInterval) {
        clearInterval(pollingInterval);
        pollingInterval = null;
    }
    activePrinterId = null;
    document.body.className = "bg-gray-900 text-gray-100 font-sans min-h-screen flex items-center justify-center";
    document.getElementById("main-panel").classList.add("hidden");
    document.getElementById("auth-box").classList.remove("hidden");
    checkAuthStatus();
}

async function loadSessions() {
    try {
        const response = await secureFetch("/api/auth/sessions");
        const data = await response.json();
        const listDiv = document.getElementById("sessions-list");
        listDiv.innerHTML = "";
        
        data.forEach(sess => {
            const item = document.createElement("div");
            item.className = "flex items-center justify-between bg-gray-900 p-2.5 rounded text-xs border border-gray-950";
            const currentBadge = sess.is_current ? `<span class="bg-blue-900/60 text-blue-300 px-1 py-0.5 rounded text-[9px] font-bold">Цей пристрій</span>` : "";
            
            item.innerHTML = `
                <div>
                    <span class="font-bold text-gray-200 block">${sess.device} ${currentBadge}</span>
                    <span class="text-gray-500 font-mono text-[10px]">${sess.ip} | ${sess.date}</span>
                </div>
                ${sess.is_current ? "" : `<button onclick="revokeSession('${sess.token}')" class="bg-rose-950/60 hover:bg-rose-900/80 text-rose-300 px-2 py-1 rounded transition text-[10px] font-bold">Закрити</button>`}
            `;
            listDiv.appendChild(item);
        });
    } catch (e) {
        console.error("Помилка завантаження сесій:", e);
    }
}

async function revokeSession(tokenToRevoke) {
    if (!confirm("Ви дійсно хочете закрити сесію для цього пристрою?")) return;
    try {
        const response = await secureFetch("/api/auth/sessions/revoke", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({token: tokenToRevoke})
        });
        const result = await response.json();
        if (result.status === "success") {
            loadSessions();
        }
    } catch (e) {
        alert("Помилка закриття сесії.");
    }
}