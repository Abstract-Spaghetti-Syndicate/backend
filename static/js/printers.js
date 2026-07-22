async function loadPrinterTabs() {
    try {
        const response = await secureFetch("/api/printers");
        const data = await response.json();
        const container = document.getElementById("printer-tabs-container");
        container.innerHTML = "";
        
        registeredPrinters = data.printers || [];

        if (registeredPrinters.length > 0) {
            if (!activePrinterId) {
                activePrinterId = registeredPrinters[0].id;
            }

            registeredPrinters.forEach(printer => {
                const btn = document.createElement("button");
                const isActive = printer.id === activePrinterId;
                
                btn.className = isActive 
                    ? "flex items-center gap-1.5 bg-blue-600 hover:bg-blue-500 text-white text-[10px] font-extrabold px-3 py-1 rounded transition uppercase tracking-wider"
                    : "flex items-center gap-1.5 bg-gray-900 hover:bg-gray-800 text-gray-400 text-[10px] font-extrabold px-3 py-1 rounded transition uppercase tracking-wider border border-gray-800";
                
                if (isActive) {
                    btn.innerHTML = `
                        <span>${printer.name}</span>
                        <span class="text-xs hover:text-blue-200 transition" title="Змінити назву" onclick="renamePrinter(event, ${printer.id}, '${printer.name}')">✏️</span>
                    `;
                } else {
                    btn.innerText = printer.name;
                }

                btn.onclick = (e) => {
                    if (e.target.tagName !== 'SPAN' || !e.target.title) {
                        activePrinterId = printer.id;
                        loadPrinterTabs();
                        pollStatus();
                    }
                };
                container.appendChild(btn);
            });
        } else {
            container.innerHTML = '<p class="text-xs text-gray-500 py-1 mr-2">Жодного принтера ще не додано.</p>';
            activePrinterId = null;
        }

    } catch (e) {
        console.error("Помилка завантаження вкладок принтерів:", e);
    }
}

async function renamePrinter(event, printerId, currentName) {
    event.stopPropagation(); 
    
    const newName = prompt("Введіть нову назву для цього принтера:", currentName);
    
    if (newName && newName.trim() !== "" && newName !== currentName) {
        try {
            const response = await secureFetch(`/api/printers/${printerId}/rename`, {
                method: "PUT",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({ name: newName.trim() })
            });
            const result = await response.json();
            if (response.ok && result.status === "success") {
                loadPrinterTabs();
            } else {
                alert("Помилка сервера: " + (result.detail || JSON.stringify(result)));
            }
        } catch (e) {
            alert("Помилка з'єднання: " + e.message);
        }
    }
}

async function pollStatus() {
    if (!activePrinterId) {
        document.getElementById("current-ip").innerText = "Не налаштовано";
        document.getElementById("connection-status").innerText = "НЕМАЄ ЗВ'ЯЗКУ (NOT_CONFIGURED)";
        document.getElementById("connection-status").className = "px-2 py-0.5 rounded text-[10px] font-bold bg-rose-950 text-rose-300";
        document.getElementById("temp-extruder").innerText = "0.0°C";
        document.getElementById("target-extruder").innerText = "Ціль: 0°C";
        document.getElementById("temp-bed").innerText = "0.0°C";
        document.getElementById("target-bed").innerText = "Ціль: 0°C";
        document.getElementById("dynamic-sensors-container").innerHTML = '<p class="text-xs text-gray-500 text-center py-8">Додайте принтер у меню праворуч.</p>';
        return;
    }

    try {
        const response = await secureFetch("/api/printers/" + activePrinterId + "/status");
        const data = await response.json();
        
        const printerInfo = registeredPrinters.find(p => p.id === activePrinterId);
        const hostStr = printerInfo ? `${printerInfo.host}:${printerInfo.port} (${printerInfo.type.toUpperCase()})` : "...";
        
        document.getElementById("current-ip").innerText = hostStr;
        
        const statusEl = document.getElementById("connection-status");
        if (data.connected) {
            statusEl.innerText = "ПІДКЛЮЧЕНО (" + data.telemetry.print_state.toUpperCase() + ")";
            statusEl.className = "px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-900 text-emerald-300";
        } else {
            statusEl.innerText = "НЕМАЄ ЗВ'ЯЗКУ (" + data.telemetry.print_state.toUpperCase() + ")";
            statusEl.className = "px-2 py-0.5 rounded text-[10px] font-bold bg-rose-950 text-rose-300";
        }

        const temps = data.telemetry.temps || { extruder: {current: 0, target: 0}, bed: {current: 0, target: 0} };
        document.getElementById("temp-extruder").innerText = temps.extruder.current.toFixed(1) + "°C";
        document.getElementById("target-extruder").innerText = "Ціль: " + temps.extruder.target.toFixed(0) + "°C";
        document.getElementById("temp-bed").innerText = temps.bed.current.toFixed(1) + "°C";
        document.getElementById("target-bed").innerText = "Ціль: " + temps.bed.target.toFixed(0) + "°C";

        const container = document.getElementById("dynamic-sensors-container");
        const rawTelemetry = data.telemetry.raw_telemetry || {};

        if (Object.keys(rawTelemetry).length === 0) {
            container.innerHTML = '<p class="text-xs text-gray-500 text-center py-8">Немає додаткових активних датчиків.</p>';
            return;
        }

        container.innerHTML = "";
        
        for (const [sensorName, sensorValue] of Object.entries(rawTelemetry)) {
            if (sensorName === "job") continue;

            const card = document.createElement("div");
            card.className = "bg-gray-900 p-2.5 rounded border border-gray-800";

            let html = `<p class="text-[11px] font-bold text-blue-400 border-b border-gray-800 pb-0.5 font-mono">${sensorName}</p>`;
            
            if (typeof sensorValue === "object" && sensorValue !== null) {
                html += `<div class="grid grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-0.5 mt-1 text-[11px]">`;
                for (const [propName, propValue] of Object.entries(sensorValue)) {
                    const displayValue = typeof propValue === "number" ? propValue.toFixed(1) : propValue;
                    html += `
                        <div class="flex justify-between py-0.5 border-b border-gray-950">
                            <span class="text-gray-500 font-mono text-[10px]">${propName}:</span>
                            <span class="font-bold text-gray-300 font-mono text-[10px]">${displayValue}</span>
                        </div>
                    `;
                }
                html += "</div>";
            } else {
                const displayValue = typeof sensorValue === "number" ? sensorValue.toFixed(1) : sensorValue;
                html += `
                    <div class="flex justify-between text-[11px] mt-1">
                        <span class="text-gray-500 font-mono text-[10px]">value:</span>
                        <span class="font-bold text-gray-300 font-mono text-[10px]">${displayValue}</span>
                    </div>
                `;
            }
            card.innerHTML = html;
            container.appendChild(card);
        }
    } catch (e) {
        console.error("Помилка опитування статусу:", e);
    }
}

async function saveManualIP(ipFromScan = null, forcedType = null, forcedPort = null) {
    const type = forcedType || document.getElementById("printer-type-select").value;
    let apiKey = forcedType ? "" : document.getElementById("manual-api-key").value;
    
    if (forcedType === "octoprint") {
        const userKey = prompt("Цьому принтеру OctoPrint потрібен API-ключ. Будь ласка, введіть його:");
        if (userKey === null) return; 
        apiKey = userKey.trim();
        if (!apiKey) return alert("API-ключ не може бути порожнім для OctoPrint.");
    }

    let ip = ipFromScan || document.getElementById("manual-ip-input").value;
    if (forcedPort && !ip.includes(":")) {
        ip = ip + ":" + forcedPort;
    }

    let name = "";
    if (ipFromScan) {
        const userEnteredName = prompt("Введіть назву для цього принтера.\nЗалиште порожнім, щоб використати назву за замовчуванням:");
        if (userEnteredName === null) return; 
        name = userEnteredName.trim();
    } else {
        name = document.getElementById("manual-printer-name").value.trim();
    }

    if (!name) {
        const cleanIp = ipFromScan || ip;
        name = type.toUpperCase() + " (" + cleanIp + ")";
    }

    if (!ip) return alert("Будь ласка, введіть коректну IP-адресу.");

    try {
        const response = await secureFetch("/settings/printer-ip", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                ip: ip,
                type: type,
                api_key: apiKey,
                name: name
            })
        });
        const result = await response.json();
        if (result.status === "success") {
            alert("Принтер '" + result.name + "' успішно збережено.");
            document.getElementById("manual-ip-input").value = "";
            document.getElementById("manual-api-key").value = "";
            document.getElementById("manual-printer-name").value = "";
            
            await loadPrinterTabs();
            loadSessions();
        }
    } catch (e) {
        alert("Помилка збереження.");
    }
}

async function startScan() {
    const scanBtn = document.getElementById("scan-btn");
    const resultsDiv = document.getElementById("scan-results");
    const listDiv = document.getElementById("printers-list");

    scanBtn.innerText = "⏳ Йде сканування мережі (2 сек)...";
    scanBtn.disabled = true;

    try {
        const response = await secureFetch("/settings/scan", { method: "POST" });
        const data = await response.json();
        
        listDiv.innerHTML = "";
        resultsDiv.classList.remove("hidden");

        if (data.status === "success" && data.printers.length > 0) {
            data.printers.forEach(printer => {
                const item = document.createElement("div");
                item.className = "flex items-center justify-between bg-gray-900 p-2 rounded text-xs border border-gray-950";
                item.innerHTML = `
                    <div>
                        <span class="font-bold text-gray-200 block">${printer.name} [${printer.type.toUpperCase()}]</span>
                        <span class="text-gray-500 font-mono">${printer.ip}:${printer.port}</span>
                    </div>
                    <button onclick="saveManualIP('${printer.ip}', '${printer.type}', '${printer.port}')" class="bg-emerald-600 hover:bg-emerald-500 px-3 py-1 rounded text-white font-bold transition">Підключити</button>
                `;
                listDiv.appendChild(item);
            });
        } else {
            listDiv.innerHTML = '<p class="text-xs text-gray-500 p-2">Пристроїв не знайдено.</p>';
        }
    } catch (e) {
        alert("Помилка сканування.");
    } finally {
        scanBtn.innerText = "🔍 Сканувати мережу";
        scanBtn.disabled = false;
    }
}

function togglePrinterTypeFields() {
    const select = document.getElementById("printer-type-select");
    const apiKeyContainer = document.getElementById("api-key-container");
    const ipInput = document.getElementById("manual-ip-input");
    const ipLabel = document.getElementById("ip-input-label");
    const apiKeyLabel = apiKeyContainer.querySelector("label");

    if (select.value === "klipper") {
        apiKeyContainer.classList.add("hidden");
        ipLabel.innerText = "IP-адреса або хост Klipper:";
        ipInput.placeholder = "напр. 192.168.1.115 або localhost";
    } else if (select.value === "octoprint") {
        apiKeyContainer.classList.remove("hidden");
        if (apiKeyLabel) apiKeyLabel.innerText = "OctoPrint API Key:";
        ipLabel.innerText = "IP-адреса або хост OctoPrint (з портом):";
        ipInput.placeholder = "напр. 100.120.186.58:5000";
    } else if (select.value === "reprap") {
        apiKeyContainer.classList.remove("hidden");
        if (apiKeyLabel) apiKeyLabel.innerText = "Пароль до плати (якщо є):";
        ipLabel.innerText = "IP-адреса або хост Duet/RepRap:";
        ipInput.placeholder = "напр. 192.168.1.120";
    }
}