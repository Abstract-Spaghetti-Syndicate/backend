let currentTab = 'spools';

function switchInventoryTab(tabName) {
    currentTab = tabName;
    const tabs = ['spools', 'filaments', 'vendors', 'locations'];

    tabs.forEach(tab => {
        const btn = document.getElementById(`tab-btn-${tab}`);
        const container = document.getElementById(`inventory-${tab}`);
        
        if (tab === tabName) {
            btn.className = "bg-blue-600 text-white px-4 py-1.5 rounded text-xs font-bold transition";
            container.classList.remove('hidden');
        } else {
            btn.className = "bg-gray-900 text-gray-400 hover:text-gray-200 px-4 py-1.5 rounded text-xs font-bold transition border border-gray-800";
            container.classList.add('hidden');
        }
    });

    // Оновлюємо текст кнопки "Додати"
    const addBtnText = document.getElementById('crud-add-text');
    if (addBtnText) {
        if (tabName === 'spools') addBtnText.innerText = "Додати котушку";
        if (tabName === 'filaments') addBtnText.innerText = "Додати філамент";
        if (tabName === 'vendors') addBtnText.innerText = "Додати виробника";
        if (tabName === 'locations') addBtnText.innerText = "Додати місце";
    }

    if (tabName === 'spools') loadSpools();
    else if (tabName === 'filaments') loadFilaments();
    else if (tabName === 'vendors') loadVendors();
    else if (tabName === 'locations') loadLocations();
}

async function loadSpools() {
    try {
        const response = await secureFetch("/api/spools");
        const data = await response.json();
        const container = document.getElementById("inventory-spools");
        container.innerHTML = "";
        dbCache.spools = {};

        if (data.status === "success" && data.spools.length > 0) {
            data.spools.forEach(item => {
                dbCache.spools[item.id] = item;
                const remaining = item.initial_weight - item.used_weight;
                const percentage = Math.max(0, Math.min(100, (remaining / item.initial_weight) * 100));
                
                container.innerHTML += `
                    <div class="bg-gray-900 p-3.5 rounded border border-gray-800 flex flex-col relative group">
                        <button onclick="openCrudModal('spools', ${item.id})" class="absolute top-2 right-2 bg-gray-800 hover:bg-gray-700 p-1 rounded opacity-0 group-hover:opacity-100 transition z-10 text-xs">✏️</button>
                        <div class="flex justify-between items-start mb-1 pr-6">
                            <span class="text-gray-500 font-mono text-[10px] font-bold uppercase tracking-wider">${item.vendor || "Невідомо"}</span>
                            <span class="bg-blue-950/60 text-blue-300 text-[9px] font-bold px-1.5 py-0.5 rounded-full uppercase">${item.material || "?"}</span>
                        </div>
                        <h3 class="text-xs font-bold text-gray-200 flex items-center mb-3">
                            ${item.color_hex ? `<span class="inline-block w-3 h-3 rounded-full border border-gray-700 mr-1.5 align-middle" style="background-color: #${item.color_hex}"></span>` : ""}
                            ${item.name || "Філамент #" + item.id}
                        </h3>
                        <div class="space-y-1">
                            <div class="flex justify-between text-[11px]"><span class="text-gray-400">Залишилося:</span><span class="font-mono font-bold text-emerald-400">${remaining.toFixed(0)}г / ${item.initial_weight.toFixed(0)}г</span></div>
                            <div class="w-full bg-gray-800 rounded-full h-1.5 overflow-hidden">
                                <div class="bg-emerald-500 h-1.5 rounded-full transition-all duration-500" style="width: ${percentage}%"></div>
                            </div>
                        </div>
                    </div>`;
            });
        } else {
            container.innerHTML = '<p class="text-xs text-gray-500 py-6 text-center col-span-full">У вашій базі немає жодної активної котушки.</p>';
        }
    } catch (e) {}
}

async function loadFilaments() {
    try {
        const response = await secureFetch("/api/filaments");
        const data = await response.json();
        const container = document.getElementById("inventory-filaments");
        container.innerHTML = "";
        dbCache.filaments = {};

        if (data.status === "success" && data.filaments.length > 0) {
            data.filaments.forEach(item => {
                dbCache.filaments[item.id] = item;
                container.innerHTML += `
                    <div class="bg-gray-900 p-3.5 rounded border border-gray-800 flex flex-col relative group">
                        <button onclick="openCrudModal('filaments', ${item.id})" class="absolute top-2 right-2 bg-gray-800 hover:bg-gray-700 p-1 rounded opacity-0 group-hover:opacity-100 transition z-10 text-xs">✏️</button>
                        <div class="flex justify-between items-start mb-1 pr-6">
                            <span class="text-gray-500 font-mono text-[10px] font-bold uppercase">ID: ${item.id}</span>
                            <span class="bg-purple-950/60 text-purple-300 text-[9px] font-bold px-1.5 py-0.5 rounded-full uppercase">${item.material || "?"}</span>
                        </div>
                        <h3 class="text-xs font-bold text-gray-200 flex items-center mb-3">
                            ${item.color_hex ? `<span class="inline-block w-3 h-3 rounded-full border border-gray-700 mr-1.5 align-middle" style="background-color: #${item.color_hex}"></span>` : ""} 
                            ${item.name || "Без назви"}
                        </h3>
                        <div class="text-[10px] text-gray-400 space-y-1">
                            <p class="flex justify-between border-b border-gray-800 pb-1"><span>Діаметр:</span> <span class="text-gray-200">${item.diameter || 1.75} мм</span></p>
                            <p class="flex justify-between border-b border-gray-800 pb-1 pt-1"><span>Щільність:</span> <span class="text-gray-200">${item.density || 0} г/см³</span></p>
                            <p class="flex justify-between pt-1"><span>Темп. (сопло/стіл):</span> <span class="text-gray-200 font-mono">${item.ext_temp || '-'}° / ${item.bed_temp || '-'}°</span></p>
                        </div>
                    </div>`;
            });
        } else {
            container.innerHTML = '<p class="text-xs text-gray-500 py-6 text-center col-span-full">Немає збереженого філаменту.</p>';
        }
    } catch (e) {}
}

async function loadVendors() {
    try {
        const response = await secureFetch("/api/vendors");
        const data = await response.json();
        const container = document.getElementById("inventory-vendors");
        container.innerHTML = "";
        dbCache.vendors = {};

        if (data.status === "success" && data.vendors.length > 0) {
            data.vendors.forEach(item => {
                dbCache.vendors[item.id] = item;
                container.innerHTML += `
                    <div class="bg-gray-900 p-3.5 rounded border border-gray-800 flex items-center justify-between group">
                        <div class="flex items-center gap-3">
                            <div class="bg-gray-800 p-2 rounded text-xl">🏭</div>
                            <div>
                                <h3 class="text-sm font-bold text-gray-200 leading-tight">${item.name}</h3>
                                ${item.comment ? `<p class="text-[10px] text-gray-400 mt-0.5">${item.comment}</p>` : `<p class="text-[10px] text-gray-600 italic mt-0.5">Без опису</p>`}
                            </div>
                        </div>
                        <button onclick="openCrudModal('vendors', ${item.id})" class="bg-gray-800 hover:bg-gray-700 p-1.5 rounded opacity-0 group-hover:opacity-100 transition text-xs">✏️</button>
                    </div>`;
            });
        } else {
            container.innerHTML = '<p class="text-xs text-gray-500 py-6 text-center col-span-full">Немає збережених виробників.</p>';
        }
    } catch (e) {}
}

async function loadLocations() {
    try {
        const response = await secureFetch("/api/locations");
        const data = await response.json();
        const container = document.getElementById("inventory-locations");
        container.innerHTML = "";
        dbCache.locations = {};

        if (data.status === "success" && data.locations.length > 0) {
            data.locations.forEach(item => {
                dbCache.locations[item.id] = item;
                container.innerHTML += `
                    <div class="bg-gray-900 p-3.5 rounded border border-gray-800 flex items-center justify-between group">
                        <div class="flex items-center gap-3">
                            <div class="bg-gray-800 p-2 rounded text-xl">📍</div>
                            <div>
                                <h3 class="text-sm font-bold text-gray-200 leading-tight">${item.name}</h3>
                                ${item.comment ? `<p class="text-[10px] text-gray-400 mt-0.5">${item.comment}</p>` : `<p class="text-[10px] text-gray-600 italic mt-0.5">Без опису</p>`}
                            </div>
                        </div>
                        <button onclick="openCrudModal('locations', ${item.id})" class="bg-gray-800 hover:bg-gray-700 p-1.5 rounded opacity-0 group-hover:opacity-100 transition text-xs">✏️</button>
                    </div>`;
            });
        } else {
            container.innerHTML = '<p class="text-xs text-gray-500 py-6 text-center col-span-full">У базі немає збережених місць (локацій).</p>';
        }
    } catch (e) {}
}

async function importFromSpoolman(btn) {
    const url = document.getElementById("spoolman-url-input").value;
    if (!url) return alert("Будь ласка, введіть URL вашого сервера Spoolman.");
    if (!confirm("Ви дійсно хочете завантажити дані?")) return;
    const oldText = btn.innerText;
    btn.innerText = "⏳ Йде імпорт...";
    btn.disabled = true;

    try {
        const response = await secureFetch("/api/spoolman/import", {
            method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({spoolman_url: url})
        });
        if (!response.ok) return alert("Помилка імпорту");
        const result = await response.json();
        if (result.status === "success") {
            alert(`Успішно імпортовано:\n- Виробників: ${result.imported.vendors}\n- Пластику: ${result.imported.filaments}\n- Котушок: ${result.imported.spools}`);
            switchInventoryTab('spools');
        }
    } catch (e) { alert("Помилка з'єднання з сервером."); } 
    finally { btn.innerText = oldText; btn.disabled = false; }
}