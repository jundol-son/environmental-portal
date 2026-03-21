let currentFile = null;
let currentResults = [];

function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

function toggleDisplay(id, displayType) {
    const el = document.getElementById(id);
    if (el) el.style.display = displayType;
}

function closeModal() { toggleDisplay('validationModal', 'none'); }

// 8. 상세 수정 모달 (None 방지 및 필드 매핑)
async function openLogEditModal(logId) {
    if(!logId) return;
    try {
        const res = await fetch(`/integrated/api/get-log-detail/${logId}/`);
        if(!res.ok) throw new Error("데이터 응답 오류");
        const d = await res.json();
        
        // 상단 정보 및 기준치 표시
        document.getElementById('display-log-info').innerHTML = `<i class="bi bi-info-circle me-1"></i> ${d.facility_sec} <span class="text-secondary ms-2">[${d.substance_name}]</span>`;
        document.getElementById('display-log-limits').innerText = `농도기준: ${d.sub_val1} / ${d.sub_val2} | 설계용량: ${d.capa_max}`;
        
        // 폼 필드 채우기 (?? 0 연산자로 null 시 0 표시 - 4번 해결)
        document.getElementById('edit-log-id').value = d.id;
        document.getElementById('edit-log-date').value = d.date;
        document.getElementById('edit-log-time').value = d.sampling_time || "";
        document.getElementById('edit-log-value').value = d.value || 0;
        document.getElementById('edit-log-airflow').value = d.airflow || 0;
        document.getElementById('edit-log-weather').value = d.weather || "";
        document.getElementById('edit-log-temp').value = d.temp || 0;
        document.getElementById('edit-log-humidity').value = d.humidity || 0;
        document.getElementById('edit-log-pressure').value = d.pressure || 0;
        document.getElementById('edit-log-wind-dir').value = d.wind_dir || "";
        document.getElementById('edit-log-wind-speed').value = d.wind_speed || 0;
        document.getElementById('edit-log-gas-speed').value = d.gas_speed || 0;
        document.getElementById('edit-log-gas-temp').value = d.gas_temp || 0;
        document.getElementById('edit-log-water').value = d.moisture || 0;
        document.getElementById('edit-log-emission').value = d.emission_rate || 0;
        document.getElementById('edit-log-agency').value = d.agency || "";
        document.getElementById('edit-log-report').value = d.is_report_data ? "true" : "false";

        new bootstrap.Modal(document.getElementById('logEditModal')).show();
    } catch (e) {
        alert("데이터 로드 중 오류가 발생했습니다.");
    }
}

async function saveLogEdit() {
    const data = {
        id: document.getElementById('edit-log-id').value,
        date: document.getElementById('edit-log-date').value,
        sampling_time: document.getElementById('edit-log-time').value,
        value: document.getElementById('edit-log-value').value,
        airflow: document.getElementById('edit-log-airflow').value,
        weather: document.getElementById('edit-log-weather').value,
        temp: document.getElementById('edit-log-temp').value,
        humidity: document.getElementById('edit-log-humidity').value,
        pressure: document.getElementById('edit-log-pressure').value,
        wind_dir: document.getElementById('edit-log-wind-dir').value,
        wind_speed: document.getElementById('edit-log-wind-speed').value,
        gas_speed: document.getElementById('edit-log-gas-speed').value,
        gas_temp: document.getElementById('edit-log-gas-temp').value,
        moisture: document.getElementById('edit-log-water').value,
        agency: document.getElementById('edit-log-agency').value,
        is_report_data: document.getElementById('edit-log-report').value === "true"
    };

    const res = await fetch('/integrated/api/save-log-edit/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
        body: JSON.stringify(data)
    });
    if (res.ok) { alert("저장되었습니다."); location.reload(); }
    else { alert("저장 실패"); }
}

async function handleFileUpload(input) {
    if (!input.files || !input.files[0]) return;
    currentFile = input.files[0];
    toggleDisplay('loadingOverlay', 'flex');
    const formData = new FormData();
    formData.append('file', currentFile);
    try {
        const response = await fetch('/integrated/api/validate-excel/', {
            method: 'POST', body: formData, headers: { 'X-CSRFToken': getCookie('csrftoken') }
        });
        const data = await response.json();
        toggleDisplay('loadingOverlay', 'none');
        currentResults = data.results || [];
        renderValidationModal(data);
    } catch (e) {
        toggleDisplay('loadingOverlay', 'none');
        alert("업로드 처리 오류");
    }
}

function renderValidationModal(data) {
    const tbody = document.getElementById('validationTableBody');
    const summaryDiv = document.getElementById('validationSummary');
    const s = data.summary || {total:0, success:0, warning:0, error:0};
    const saveableCount = (s.success || 0) + (s.warning || 0);
    const errorCount = s.error || 0;

    summaryDiv.innerHTML = `
        <span class="badge bg-secondary p-2 me-1">전체 ${s.total || 0}건</span> 
        <span class="badge bg-success p-2 me-1">저장가능 ${saveableCount}건</span> 
        <span class="badge bg-danger p-2">오류(저장불가) ${errorCount}건</span>`;
    tbody.innerHTML = '';
    (data.results || []).forEach(item => {
        const tr = document.createElement('tr');
        if(item.status === 'error') {
            tr.className = 'table-danger';
        } else if (item.status === 'warning') {
            tr.className = 'table-warning';
        }

        const renderStatus = (status) => {
            if (status === '법적초과') return `<span class="text-danger fw-bold">${status}</span>`;
            if (status === '사내초과') return `<span class="text-warning fw-bold">${status}</span>`;
            return status || '-'; // null/undefined 경우 '-' 표시
        };

        tr.innerHTML = `
            <td>${item.row}</td>
            <td>${item.facility_name}</td>
            <td>${item.substance_name}</td>
            <td>${item.value}</td>
            <td>${renderStatus(item.legal_ref_status)}</td>
            <td>${renderStatus(item.conc_status)}</td>
            <td>${renderStatus(item.af_status)}</td>
        `;
        tbody.appendChild(tr);
    });
    toggleDisplay('validationModal', 'flex');
}

async function submitFinalData() {
    const finalData = currentResults.filter(i => i.status !== 'error' && i.facility_id).map(i => ({
        facility_id: i.facility_id, 
        substance_id: i.substance_id, 
        substance_name: i.substance_name, // 미등록 물질명 보존을 위해 추가 (6번 해결)
        date: i.date, 
        value: i.value, 
        extra_data: i.extra_data
    }));
    if(!finalData.length) { alert("저장할 수 있는 유효한 데이터가 없습니다."); return; }
    const res = await fetch('/integrated/api/save-excel-data/', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
        body: JSON.stringify({ data: finalData })
    });
    if (res.ok) location.reload();
}

function toggleAllLogs(source) { document.querySelectorAll('.log-check').forEach(cb => cb.checked = source.checked); }

async function deleteCheckedLogs() {
    const ids = Array.from(document.querySelectorAll('.log-check:checked')).map(cb => cb.value);
    if (!ids.length || !confirm("삭제하시겠습니까?")) return;
    const res = await fetch('/integrated/api/delete-selected/', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
        body: JSON.stringify({ type: 'log', ids: ids })
    });
    if (res.ok) location.reload();
}

// 필터링 함수가 dataset을 참조하도록 보강
function filterLogTable() {
    const fVal = document.getElementById('filter-facility').value.toLowerCase().trim();
    const lVal = document.getElementById('filter-line').value.toLowerCase().trim();
    const sVal = document.getElementById('filter-substance').value.toLowerCase().trim();
    const eVal = document.getElementById('filter-exceed').value;
    const aVal = document.getElementById('filter-agency').value.toLowerCase().trim();

    const rows = document.querySelectorAll('#logTable tbody tr');
    
    rows.forEach(row => {
        const sec = (row.dataset.sec || "").toLowerCase();
        const line = (row.dataset.line || "").toLowerCase();
        const substance = (row.dataset.substance || "").toLowerCase();
        const agency = (row.dataset.agency || "").toLowerCase();
        const status = (row.dataset.status || "");

        const matchFacility = sec.includes(fVal);
        const matchLine = line.includes(lVal);
        const matchSubstance = substance.includes(sVal);
        const matchAgency = agency.includes(aVal);
        
        let matchExceed = (eVal === "") || (status === eVal);

        if (matchFacility && matchLine && matchSubstance && matchAgency && matchExceed) {
            row.style.display = "";
        } else {
            row.style.display = "none";
        }
    });
}

function resetLogFilter() {
    ['filter-facility', 'filter-line', 'filter-substance', 'filter-exceed', 'filter-agency'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = "";
    });
    filterLogTable();
}