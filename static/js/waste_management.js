// static/js/waste_management.js

// 1. 필터 초기화
function resetFilters() {
    window.location.href = window.location.pathname;
}

// 2. 페이지 직접 이동
function jumpToPageDirect(maxPage) {
    const pageNum = document.getElementById('directPageInput').value;
    if (!pageNum || pageNum < 1 || parseInt(pageNum) > parseInt(maxPage)) {
        return alert("페이지 번호를 확인해주세요.");
    }
    const urlParams = new URLSearchParams(window.location.search);
    urlParams.set('page', pageNum);
    window.location.href = window.location.pathname + '?' + urlParams.toString();
}

// 3. 체크박스 제어
function toggleAll(master) {
    const checkboxes = document.getElementsByClassName('waste-checkbox');
    for (let i = 0; i < checkboxes.length; i++) {
        checkboxes[i].checked = master.checked;
    }
}

function getSelectedIds() {
    return Array.from(document.querySelectorAll('.waste-checkbox:checked')).map(cb => cb.value);
}

// 4. 엑셀 다운로드
function exportSelectedExcel() {
    const ids = getSelectedIds();
    if (ids.length === 0) return alert("항목을 선택해주세요.");
    window.location.href = `/wastes/export/?${ids.map(id => `ids=${id}`).join('&')}`;
}

// 5. 보고서 생성
function generateReport() {
    const ids = getSelectedIds();
    if (ids.length === 0) return alert("보고서를 작성할 항목을 선택해주세요.");
    location.href = `/wastes/report/?${ids.map(id => `ids=${id}`).join('&')}`;
}

// 6. 메일 발송 팝업 제어
function sendSelectedMail() {
    const checkboxes = document.querySelectorAll('.waste-checkbox:checked');
    if (checkboxes.length === 0) return alert("업체를 선택해주세요.");

    let companies = [];
    checkboxes.forEach(box => {
        const row = box.closest('tr');
        companies.push(row.cells[4].innerText); // 수거업체 컬럼
    });

    document.getElementById('selectedCustomerList').innerText = Array.from(new Set(companies)).join(', ');
    new bootstrap.Modal(document.getElementById('multiMailModal')).show();
}