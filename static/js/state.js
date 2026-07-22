// Глобальні змінні стану програми
let isSystemRegistered = false;
let pollingInterval = null;
let activePrinterId = null;       
let registeredPrinters = [];      

// Універсальна функція для захищених запитів до API
async function secureFetch(url, options = {}) {
    const token = localStorage.getItem("session_token");
    if (!options.headers) options.headers = {};
    options.headers["Authorization"] = "Bearer " + token;

    const response = await fetch(url, options);
    if (response.status === 401) {
        handleLogout();
        throw new Error("Unauthorized");
    }
    return response;
}

// Запуск головного інтерфейсу
function showMainPanel() {
    document.body.className = "bg-gray-900 text-gray-100 font-sans min-h-screen flex items-start justify-start";
    document.getElementById("auth-box").classList.add("hidden");
    document.getElementById("main-panel").classList.remove("hidden");
    
    if (!pollingInterval) {
        loadPrinterTabs().then(() => {
            pollingInterval = setInterval(pollStatus, 1500);
            pollStatus();
        });
        loadSessions();
        switchInventoryTab('spools');
    }
}