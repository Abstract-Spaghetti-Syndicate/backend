let crudMode = null; // 'spools', 'filaments', 'vendors', 'locations'
let crudEditId = null; 
const dbCache = { spools: {}, filaments: {}, vendors: {}, locations: {} };

async function openCrudModal(forcedTab = null, id = null) {
    crudMode = forcedTab || currentTab;
    crudEditId = id;
    
    const modal = document.getElementById('crud-modal');
    const title = document.getElementById('crud-modal-title');
    const fields = document.getElementById('crud-form-fields');
    
    modal.classList.remove('hidden');
    fields.innerHTML = '<p class="text-xs text-gray-400 text-center">Завантаження...</p>';
    document.getElementById('crud-save-btn').innerText = id ? 'Зберегти зміни' : 'Створити';
    
    const isEdit = !!id;
    const data = isEdit ? dbCache[crudMode][id] : {};

    if (crudMode === 'vendors' || crudMode === 'locations') {
        title.innerText = isEdit ? `Редагування: ${data.name}` : (crudMode === 'vendors' ? 'Додати виробника' : 'Додати місце');
        fields.innerHTML = `
            <div><label class="block text-xs text-gray-400 mb-1">Назва *</label><input type="text" id="crud-name" value="${data.name||''}" class="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm text-white" required></div>
            <div><label class="block text-xs text-gray-400 mb-1">Коментар</label><input type="text" id="crud-comment" value="${data.comment||''}" class="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm text-white"></div>
        `;
    } 
    else if (crudMode === 'filaments') {
        title.innerText = isEdit ? `Редагувати філамент` : 'Додати філамент';
        const vRes = await secureFetch('/api/vendors'); const vData = await vRes.json();
        let vOpts = '<option value="">-- Не вказано --</option>';
        (vData.vendors||[]).forEach(v => vOpts += `<option value="${v.id}" ${data.vendor_id === v.id ? 'selected':''}>${v.name}</option>`);

        fields.innerHTML = `
            <div><label class="block text-xs text-gray-400 mb-1">Назва / Колір *</label><input type="text" id="crud-name" value="${data.name||''}" class="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm text-white" required></div>
            <div class="grid grid-cols-2 gap-3">
                <div><label class="block text-xs text-gray-400 mb-1">Виробник</label><select id="crud-vendor" class="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm text-white">${vOpts}</select></div>
                <div><label class="block text-xs text-gray-400 mb-1">Матеріал (PLA, ABS)</label><input type="text" id="crud-material" value="${data.material||''}" class="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm text-white"></div>
                <div><label class="block text-xs text-gray-400 mb-1">Діаметр (мм)</label><input type="number" step="0.01" id="crud-diam" value="${data.diameter||1.75}" class="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm text-white"></div>
                <div><label class="block text-xs text-gray-400 mb-1">Вага нетто (г)</label><input type="number" step="1" id="crud-weight" value="${data.weight||1000}" class="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm text-white"></div>
                <div><label class="block text-xs text-gray-400 mb-1">Темп. Сопла (°C)</label><input type="number" id="crud-ext" value="${data.ext_temp||''}" class="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm text-white"></div>
                <div><label class="block text-xs text-gray-400 mb-1">Темп. Столу (°C)</label><input type="number" id="crud-bed" value="${data.bed_temp||''}" class="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm text-white"></div>
            </div>
        `;
    }
    else if (crudMode === 'spools') {
        title.innerText = isEdit ? `Редагувати котушку` : 'Додати котушку';
        
        // Завантажуємо список філаментів
        const fRes = await secureFetch('/api/filaments'); 
        const fData = await fRes.json();
        let fOpts = '<option value="">-- Оберіть пластик --</option>';
        (fData.filaments || []).forEach(f => {
            fOpts += `<option value="${f.id}" ${data.filament_id === f.id ? 'selected' : ''}>${f.name} (${f.material})</option>`;
        });

        // Ініціалізуємо базові значення
        const initW = data.initial_weight || 1000;
        const spoolW = data.spool_weight || 200;
        const usedW = data.used_weight || 0;
        
        window.spoolCalcState = { mode: 'used', initial: initW, empty: spoolW, used: usedW };

        fields.innerHTML = `
            ${!isEdit 
                ? `<div><label class="block text-xs text-gray-400 mb-1">Філамент *</label><select id="crud-filament" class="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500" required>${fOpts}</select></div>` 
                : '<p class="text-xs text-blue-400 mb-2 bg-blue-900/20 p-2 rounded border border-blue-900/50">Зміна філаменту для існуючої котушки недоступна.</p>'
            }
            
            <div class="mt-3">
                <label class="block text-xs text-gray-400 mb-1">Ціна</label>
                <div class="flex">
                    <input type="number" step="0.01" id="crud-price" value="${data.price || ''}" class="w-full bg-gray-900 border border-gray-700 rounded-l px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500" placeholder="0.00">
                    <span class="bg-gray-800 border border-l-0 border-gray-700 rounded-r px-3 py-2 text-sm text-gray-400 font-mono">UAH</span>
                </div>
                <p class="text-[10px] text-gray-500 mt-1">Ціна цілої котушки. Якщо не вказано, замість неї буде використано ціну філамента.</p>
            </div>

            <div class="grid grid-cols-2 gap-3 mt-3">
                <div>
                    <label class="block text-xs text-gray-400 mb-1">Початкова вага *</label>
                    <div class="flex">
                        <input type="number" step="1" id="crud-init-w" value="${initW}" oninput="updateSpoolCalc('initial', this.value)" class="w-full bg-gray-900 border border-gray-700 rounded-l px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500" required>
                        <span class="bg-gray-800 border border-l-0 border-gray-700 rounded-r px-3 py-2 text-sm text-gray-400 font-mono">г</span>
                    </div>
                </div>
                <div>
                    <label class="block text-xs text-gray-400 mb-1">Порожня вага</label>
                    <div class="flex">
                        <input type="number" step="1" id="crud-empty-w" value="${spoolW}" oninput="updateSpoolCalc('empty', this.value)" class="w-full bg-gray-900 border border-gray-700 rounded-l px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500">
                        <span class="bg-gray-800 border border-l-0 border-gray-700 rounded-r px-3 py-2 text-sm text-gray-400 font-mono">г</span>
                    </div>
                </div>
            </div>

            <!-- ІНТЕРАКТИВНА ВАГА -->
            <div class="mt-4 border-t border-gray-800 pt-3">
                <label class="block text-sm font-bold text-gray-300 mb-2">Вага</label>
                <div class="flex gap-1 mb-3">
                    <button type="button" id="tab-w-used" onclick="setSpoolCalcMode('used')" class="flex-1 bg-gray-900 text-gray-400 border border-gray-800 text-xs py-1.5 transition rounded-sm">Використана Вага</button>
                    <button type="button" id="tab-w-remain" onclick="setSpoolCalcMode('remain')" class="flex-1 bg-gray-900 text-gray-400 border border-gray-800 text-xs py-1.5 transition rounded-sm">Залишок Ваги</button>
                    <button type="button" id="tab-w-measured" onclick="setSpoolCalcMode('measured')" class="flex-1 bg-gray-900 text-gray-400 border border-gray-800 text-xs py-1.5 transition rounded-sm">Виміряна Вага</button>
                </div>
                
                <p id="spool-active-label" class="text-[10px] text-gray-500 mb-1"></p>
                <div class="flex mb-3">
                    <input type="number" step="0.01" id="crud-active-w" oninput="updateSpoolCalc('input', this.value)" class="w-full bg-gray-900 border border-gray-700 rounded-l px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500" value="${usedW}">
                    <span class="bg-gray-800 border border-l-0 border-gray-700 rounded-r px-3 py-2 text-sm text-gray-400 font-mono">г</span>
                </div>

                <div class="bg-gray-950/50 p-2.5 rounded border border-gray-800 text-xs text-gray-400 space-y-1.5">
                    <div class="flex justify-between"><span id="lbl-w-1">Залишок Ваги:</span> <span id="val-w-1" class="font-mono text-gray-300">0 г</span></div>
                    <div class="flex justify-between"><span id="lbl-w-2">Виміряна Вага:</span> <span id="val-w-2" class="font-mono text-gray-300">0 г</span></div>
                </div>
                <input type="hidden" id="crud-used-w" value="${usedW}">
            </div>

            <div class="mt-3 border-t border-gray-800 pt-3">
                <label class="block text-xs text-gray-400 mb-1">Коментар</label>
                <textarea id="crud-comment" class="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm text-white h-16 resize-none focus:outline-none focus:border-blue-500">${data.comment || ''}</textarea>
            </div>
        `;
        
        // Активуємо першу вкладку ваги після рендеру форми
        setTimeout(() => setSpoolCalcMode('used'), 10);
    }
}

function closeCrudModal() {
    document.getElementById('crud-modal').classList.add('hidden');
    crudEditId = null;
}

async function handleCrudSubmit(e) {
    e.preventDefault();
    let payload = {};
    let endpoint = `/api/${crudMode}`;
    let method = crudEditId ? 'PUT' : 'POST';
    if (crudEditId) endpoint += `/${crudEditId}`;

    if (crudMode === 'vendors' || crudMode === 'locations') {
        payload = { name: document.getElementById('crud-name').value, comment: document.getElementById('crud-comment').value };
    } 
    else if (crudMode === 'filaments') {
        payload = {
            name: document.getElementById('crud-name').value,
            vendor_id: parseInt(document.getElementById('crud-vendor').value) || null,
            material: document.getElementById('crud-material').value,
            diameter: parseFloat(document.getElementById('crud-diam').value) || 1.75,
            weight: parseFloat(document.getElementById('crud-weight').value) || 1000,
            settings_extruder_temp: parseInt(document.getElementById('crud-ext').value) || null,
            settings_bed_temp: parseInt(document.getElementById('crud-bed').value) || null,
        };
    }
    else if (crudMode === 'spools') {
        payload = {
            initial_weight: parseFloat(document.getElementById('crud-init-w').value) || 1000,
            spool_weight: parseFloat(document.getElementById('crud-empty-w').value) || 0,
            used_weight: parseFloat(document.getElementById('crud-used-w').value) || 0,
            price: parseFloat(document.getElementById('crud-price').value) || null,
            comment: document.getElementById('crud-comment').value
        };
        if (!crudEditId) {
            payload.filament_id = parseInt(document.getElementById('crud-filament').value);
            if (!payload.filament_id) return alert("Оберіть філамент!");
        } else {
            payload.filament_id = dbCache[crudMode][crudEditId].filament_id; // Беремо зі старого кешу
        }
    }

    try {
        const res = await secureFetch(endpoint, { method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) });
        if (res.ok) {
            closeCrudModal();
            switchInventoryTab(crudMode); // Оновлюємо список
        } else {
            const err = await res.json();
            alert("Помилка: " + JSON.stringify(err));
        }
    } catch (error) { alert("Помилка з'єднання"); }
}

// --- ЛОГІКА ІНТЕРАКТИВНОЇ ВАГИ ---
window.spoolCalcState = { mode: 'used', initial: 1000, empty: 200, used: 0 };

function setSpoolCalcMode(mode) {
    window.spoolCalcState.mode = mode;
    ['used', 'remain', 'measured'].forEach(t => {
        const btn = document.getElementById('tab-w-' + t);
        if(btn) btn.className = (t === mode) 
            ? "flex-1 bg-orange-900/60 text-orange-400 border border-orange-700 text-xs py-1.5 transition font-bold rounded-sm"
            : "flex-1 bg-gray-900 text-gray-400 border border-gray-800 text-xs py-1.5 transition hover:bg-gray-800 rounded-sm";
    });

    const activeLabel = document.getElementById('spool-active-label');
    const input = document.getElementById('crud-active-w');
    const lbl1 = document.getElementById('lbl-w-1');
    const lbl2 = document.getElementById('lbl-w-2');

    let init = parseFloat(window.spoolCalcState.initial) || 0;
    let empty = parseFloat(window.spoolCalcState.empty) || 0;
    let used = parseFloat(window.spoolCalcState.used) || 0;

    if (mode === 'used') {
        activeLabel.innerText = "Скільки філаменту було використано з котушки (г).";
        input.value = used.toFixed(2);
        lbl1.innerText = "Залишок Ваги:"; lbl2.innerText = "Виміряна Вага (Брутто):";
    } else if (mode === 'remain') {
        activeLabel.innerText = "Скільки філаменту залишилося на котушці (г).";
        input.value = Math.max(0, init - used).toFixed(2);
        lbl1.innerText = "Використана Вага:"; lbl2.innerText = "Виміряна Вага (Брутто):";
    } else if (mode === 'measured') {
        activeLabel.innerText = "Яка вага філаменту та котушки на вагах (г).";
        input.value = Math.max(0, init + empty - used).toFixed(2);
        lbl1.innerText = "Використана Вага:"; lbl2.innerText = "Залишок Ваги:";
    }
    updateSpoolCalcLabels();
}

function updateSpoolCalc(field, value) {
    let val = parseFloat(value) || 0;
    if (field === 'initial') window.spoolCalcState.initial = val;
    if (field === 'empty') window.spoolCalcState.empty = val;
    
    let mode = window.spoolCalcState.mode;
    let init = window.spoolCalcState.initial;
    let empty = window.spoolCalcState.empty;
    let activeVal = parseFloat(document.getElementById('crud-active-w').value) || 0;

    if (mode === 'used') window.spoolCalcState.used = activeVal;
    else if (mode === 'remain') window.spoolCalcState.used = init - activeVal;
    else if (mode === 'measured') window.spoolCalcState.used = init + empty - activeVal;
    
    if(window.spoolCalcState.used < 0) window.spoolCalcState.used = 0;
    if(window.spoolCalcState.used > init) window.spoolCalcState.used = init;

    document.getElementById('crud-used-w').value = window.spoolCalcState.used;
    updateSpoolCalcLabels();
}

function updateSpoolCalcLabels() {
    let mode = window.spoolCalcState.mode;
    let init = window.spoolCalcState.initial;
    let empty = window.spoolCalcState.empty;
    let used = window.spoolCalcState.used;
    let remain = init - used;
    let measured = remain + empty;

    const val1 = document.getElementById('val-w-1');
    const val2 = document.getElementById('val-w-2');

    if(val1 && val2) {
        if (mode === 'used') {
            val1.innerText = remain.toFixed(2) + " г"; val2.innerText = measured.toFixed(2) + " г";
        } else if (mode === 'remain') {
            val1.innerText = used.toFixed(2) + " г"; val2.innerText = measured.toFixed(2) + " г";
        } else if (mode === 'measured') {
            val1.innerText = used.toFixed(2) + " г"; val2.innerText = remain.toFixed(2) + " г";
        }
    }
}