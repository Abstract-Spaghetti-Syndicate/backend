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
        const fRes = await secureFetch('/api/filaments'); const fData = await fRes.json();
        let fOpts = '<option value="">-- Оберіть пластик --</option>';
        (fData.filaments||[]).forEach(f => fOpts += `<option value="${f.id}">${f.name} (${f.material})</option>`);

        fields.innerHTML = `
            ${!isEdit ? `<div><label class="block text-xs text-gray-400 mb-1">Філамент (Матеріал) *</label><select id="crud-filament" class="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm text-white" required>${fOpts}</select></div>` : '<p class="text-xs text-blue-400 mb-2">Зміна філаменту для існуючої котушки тимчасово недоступна.</p>'}
            <div class="grid grid-cols-2 gap-3">
                <div><label class="block text-xs text-gray-400 mb-1">Початкова вага (г) *</label><input type="number" step="1" id="crud-init-w" value="${data.initial_weight||1000}" class="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm text-white" required></div>
                <div><label class="block text-xs text-gray-400 mb-1">Витрачено (г) *</label><input type="number" step="0.1" id="crud-used-w" value="${data.used_weight||0}" class="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm text-white" required></div>
            </div>
        `;
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
            used_weight: parseFloat(document.getElementById('crud-used-w').value) || 0,
        };
        if (!crudEditId) {
            payload.filament_id = parseInt(document.getElementById('crud-filament').value);
            if (!payload.filament_id) return alert("Оберіть філамент!");
        } else {
            payload.filament_id = 1; // Заглушка, оскільки PUT вимагає id
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