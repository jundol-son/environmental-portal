let currentFile = null;
let currentResults = [];

// 1. 장고 보안 CSRF 토큰 획득
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

// 2. UI 제어 유틸리티
function toggleDisplay(id, displayType) {
    const el = document.getElementById(id);
    if (el) el.style.display = displayType;
}

function closeModal() { toggleDisplay('validationModal', 'none'); }
function closeSheetModal() { toggleDisplay('sheetModal', 'none'); }

// 3. 대시보드 메인 로직: 실시간 필터링
function filterLogTable() {
    const fVal = document.getElementById('filter-facility').value.toLowerCase().trim();
    const lVal = document.getElementById('filter-line').value.toLowerCase().trim();
    const sVal = document.getElementById('filter-substance').value.toLowerCase().trim();
    const eVal = document.getElementById('filter-exceed').value;
    const aVal = document.getElementById('filter-agency').value.toLowerCase().trim();

    const rows = document.querySelectorAll('#logTable tbody tr');
    
    rows.forEach(row => {
        // data- 속성에서 값을 직접 추출
        const sec = (row.dataset.sec || "").toLowerCase();
        const line = (row.dataset.line || "").toLowerCase();
        const substance = (row.dataset.substance || "").toLowerCase();
        const agency = (row.dataset.agency || "").toLowerCase();
        const status = (row.dataset.status || "");

        const matchFacility = sec.includes(fVal);
        const matchLine = line.includes(lVal);
        const matchSubstance = substance.includes(sVal);
        const matchAgency = agency.includes(aVal);
        
        let matchExceed = false;
        if (eVal === "") matchExceed = true;
        else if (eVal === "초과") matchExceed = status.includes("초과");
        else matchExceed = (status === eVal);

        row.style.display = (matchFacility && matchLine && matchSubstance && matchAgency && matchExceed) ? "" : "none";
    });
}

function resetLogFilter() {
    ['filter-facility', 'filter-line', 'filter-substance', 'filter-exceed', 'filter-agency'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = "";
    });
    filterLogTable();
}

async function openLogEditModal(logId) {
    if(!logId) return;
    try {
        const res = await fetch(`/integrated/api/get-log-detail/${logId}/`);
        if(!res.ok) throw new Error("데이터 조회 실패");
        const d = await res.json();
        
        // 데이터 매핑 (HTML ID와 d 객체 필드명 일치 확인)
        document.getElementById('edit-log-id').value = d.id;
        document.getElementById('display-log-info').innerText = `${d.facility_sec} [${d.substance_name}]`;
        
        document.getElementById('edit-log-date').value = d.date;
        document.getElementById('edit-log-time').value = d.sampling_time || "";
        document.getElementById('edit-log-value').value = d.value;
        
        document.getElementById('edit-log-weather').value = d.weather || "";
        document.getElementById('edit-log-temp').value = d.temp || 0;
        document.getElementById('edit-log-humidity').value = d.humidity || 0;
        document.getElementById('edit-log-pressure').value = d.pressure || 0;
        
        document.getElementById('edit-log-wind-dir').value = d.wind_dir || "";
        document.getElementById('edit-log-wind-speed').value = d.wind_speed || 0;
        document.getElementById('edit-log-gas-speed').value = d.gas_speed || 0; // views.py에 맞춰 추가 필요시 대응
        document.getElementById('edit-log-gas-temp').value = d.gas_temp || 0;
        
        document.getElementById('edit-log-airflow').value = d.airflow || 0;
        document.getElementById('edit-log-water').value = d.humidity || 0; // 수분함량 필드 매핑
        document.getElementById('edit-log-emission').value = d.emission_rate || 0;
        document.getElementById('edit-log-agency').value = d.agency || "";

        const modalEl = document.getElementById('logEditModal');
        bootstrap.Modal.getOrCreateInstance(modalEl).show();
    } catch (e) {
        alert("데이터를 불러오는 중 에러가 발생했습니다.");
    }
}

async function saveLogEdit() {
    const data = {
        id: document.getElementById('edit-log-id').value,
        date: document.getElementById('edit-log-date').value,
        sampling_time: document.getElementById('edit-log-time').value,
        value: document.getElementById('edit-log-value').value,
        weather: document.getElementById('edit-log-weather').value,
        temp: document.getElementById('edit-log-temp').value,
        humidity: document.getElementById('edit-log-humidity').value,
        pressure: document.getElementById('edit-log-pressure').value,
        wind_dir: document.getElementById('edit-log-wind-dir').value,
        wind_speed: document.getElementById('edit-log-wind-speed').value,
        airflow: document.getElementById('edit-log-airflow').value,
        emission_rate: document.getElementById('edit-log-emission').value,
        agency: document.getElementById('edit-log-agency').value,
        // 추가된 항목들 (가스속도 등 views.py 수신 대기 항목)
        gas_speed: document.getElementById('edit-log-gas-speed').value,
        gas_temp: document.getElementById('edit-log-gas-temp').value,
        water_content: document.getElementById('edit-log-water').value
    };

    try {
        const res = await fetch('/integrated/api/save-log-edit/', {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json', 
                'X-CSRFToken': getCookie('csrftoken') 
            },
            body: JSON.stringify(data)
        });

        if (res.ok) {
            alert("저장되었습니다.");
            location.reload();
        } else {
            alert("저장 실패");
        }
    } catch (e) {
        alert("통신 오류 발생");
    }
}

async function deleteLogData() {
    const id = document.getElementById('edit-log-id').value;
    if(!confirm("이 측정 데이터를 삭제하시겠습니까?")) return;
    
    const res = await fetch('/integrated/api/delete-log/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
        body: JSON.stringify({ id: id })
    });
    if (res.ok) location.reload();
}

// 5. 엑셀 파일 업로드 및 유효성 검사 로직
async function handleFileUpload(input) {
    if (!input.files || !input.files[0]) return;
    currentFile = input.files[0];
    toggleDisplay('loadingOverlay', 'flex');

    const formData = new FormData();
    formData.append('file', currentFile);

    try {
        const response = await fetch('/integrated/api/validate-excel/', {
            method: 'POST',
            body: formData,
            headers: { 'X-CSRFToken': getCookie('csrftoken') }
        });
        const data = await response.json();
        toggleDisplay('loadingOverlay', 'none');

        if (data.requires_sheet_selection) {
            openSheetModal(data.sheets);
        } else {
            currentResults = data.results || [];
            renderValidationModal(data);
        }
    } catch (error) {
        toggleDisplay('loadingOverlay', 'none');
        alert("분석 중 오류가 발생했습니다.");
    }
}

/**
 * 엑셀 분석 결과를 표(Table) 형식으로 모달에 렌더링합니다.
 * 누락 알림 대신 업로드된 개별 행의 초과 여부와 설비 정보를 보여줍니다.
 */
function renderValidationModal(data) {
    const tbody = document.getElementById('validationTableBody');
    const summaryDiv = document.getElementById('validationSummary');
    
    // 1. 상단 요약 정보 업데이트 (전체/정상/초과/에러)
    const s = data.summary || {total:0, success:0, exceed:0, error:0};
    summaryDiv.innerHTML = `
        <span class="badge bg-secondary p-2">전체 ${s.total}건</span>
        <span class="badge bg-success p-2">정상 ${s.success}건</span>
        <span class="badge bg-danger p-2">기준초과 ${s.exceed}건</span>
        <span class="badge bg-warning text-dark p-2">입력오류 ${s.error}건</span>
    `;

    // 2. 테이블 데이터 렌더링
    tbody.innerHTML = '';
    const results = data.results || [];
    
    results.forEach(item => {
        const tr = document.createElement('tr');
        const extra = item.extra_data || {};
        
        // 상태별 배지 및 스타일 결정
        let statusBadge = '';
        let rowClass = '';
        let valueClass = 'text-primary';

        if(item.status === 'success') {
            statusBadge = `<span class="badge bg-success-subtle text-success">정상</span>`;
        } else if(item.status === 'warning') {
            statusBadge = `<span class="badge bg-warning-subtle text-warning">사내초과</span>`;
            rowClass = 'table-warning-light';
        } else if(item.status === 'danger') {
            statusBadge = `<span class="badge bg-danger">법적초과</span>`;
            rowClass = 'table-danger-light';
            valueClass = 'text-danger';
        } else {
            statusBadge = `<span class="badge bg-dark">설비오류</span>`;
            rowClass = 'table-light';
        }

        tr.className = rowClass;
        tr.innerHTML = `
            <td class="text-center text-muted small">${item.row}</td>
            <td><strong>${item.facility_name || '미등록'}</strong></td>
            <td>${item.date}</td>
            <td><span class="badge border text-dark bg-white fw-normal">${item.substance_name}</span></td>
            <td class="text-end fw-bold ${valueClass}">${item.value}</td>
            <td>
                <small class="d-block">풍량: ${extra.air_flow || '0'}</small>
                <small class="text-muted">${extra.weather || '-'} / ${extra.temp || '0'}℃</small>
            </td>
            <td class="text-end text-info fw-bold">${extra.emission_rate || '0'}</td>
            <td class="text-center">${statusBadge}<br><small class="text-muted" style="font-size:0.7rem;">${item.msg}</small></td>
        `;
        tbody.appendChild(tr);
    });

    // 미측정 항목 알림창은 이제 필요 없으므로 숨김 처리 (또는 HTML에서 제거)
    const missingDiv = document.getElementById('missingEntries');
    if(missingDiv) missingDiv.classList.add('d-none');

    // 모달 표시
    const modal = document.getElementById('validationModal');
    if (modal) modal.style.display = 'flex';
}

async function submitFinalData() {
    const finalData = [];
    currentResults.forEach((item, idx) => {
        if (item.status === 'error' || !item.facility_id) return;
        const select = document.querySelector(`.action-select[data-idx="${idx}"]`);
        const action = select ? select.value : 'update';
        if (action === 'update') {
            finalData.push({
                facility_id: item.facility_id,
                substance_id: item.substance_id,
                date: item.date,
                value: item.value,
                extra_data: item.extra_data
            });
        }
    });

    if (finalData.length === 0) return alert("저장할 데이터가 없습니다.");
    
    try {
        const response = await fetch('/integrated/api/save-excel-data/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
            body: JSON.stringify({ data: finalData })
        });
        if (response.ok) {
            alert("성공적으로 저장되었습니다.");
            location.reload();
        } else {
            alert("저장 실패");
        }
    } catch (e) { alert("통신 오류 발생"); }
}

function openSheetModal(sheets) {
    const list = document.getElementById('sheetList');
    if(list) {
        list.innerHTML = sheets.map(s => `
            <button class="btn btn-outline-primary text-start p-3 mb-2 shadow-sm d-flex justify-content-between" onclick="validateWithSheet('${s}')">
                ${s} <i class="bi bi-chevron-right"></i>
            </button>`).join('');
    }
    toggleDisplay('sheetModal', 'flex');
}

async function validateWithSheet(sheetName) {
    closeSheetModal();
    toggleDisplay('loadingOverlay', 'flex');
    const formData = new FormData();
    formData.append('file', currentFile);
    formData.append('sheet_name', sheetName);

    try {
        const response = await fetch('/integrated/api/validate-excel/', {
            method: 'POST',
            body: formData,
            headers: { 'X-CSRFToken': getCookie('csrftoken') }
        });
        const data = await response.json();
        toggleDisplay('loadingOverlay', 'none');
        currentResults = data.results || [];
        renderValidationModal(data);
    } catch (error) {
        toggleDisplay('loadingOverlay', 'none');
        alert("시트 분석 오류");
    }
}