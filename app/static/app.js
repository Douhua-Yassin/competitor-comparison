let currentRange = 'all';
let currentLineId = null;
let pollingTimer = null;

const esc = value => String(value ?? '').replace(/[&<>"]/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'
}[char]));

function setStatus(message, isError = false) {
  const node = document.querySelector('#status');
  node.textContent = message;
  node.classList.toggle('error', isError);
}

function renderTabs(lines, selectedId) {
  const nav = document.querySelector('#productLines');
  nav.innerHTML = lines.map(line => `
    <button type="button" class="tab ${line.id === selectedId ? 'active' : ''}" data-line-id="${line.id}">
      ${esc(line.name)}
    </button>
  `).join('');
  nav.querySelectorAll('[data-line-id]').forEach(button => {
    button.onclick = () => {
      currentLineId = Number(button.dataset.lineId);
      loadTable();
    };
  });
}

function renderCell(cell) {
  const record = cell.record;
  if (!record) return '<td class="date empty-cell">—</td>';
  if (!['success', 'partial_success'].includes(record.crawl_status)) {
    return `<td class="date failed">
      抓取失败
      <details><summary>详情</summary>
        ${esc(record.error_message || record.crawl_status)}<br>
        抓取时间：${esc(record.captured_at)}
      </details>
    </td>`;
  }
  const price = record.price_text || (record.price != null ? `$${record.price}` : '—');
  const details = [
    `排名：${esc(record.rank_text || '—')}`,
    `星级：${esc(record.rating_value ?? '—')}`,
    `评价：${esc(record.review_count ?? '—')}`,
    `数据来源：${esc(record.data_source || '—')}`,
    `卖家精灵：${esc(record.seller_sprite_status || '—')}`,
    `配送位置：${esc(record.delivery_status || '—')}`,
    record.error_message ? `提示：${esc(record.error_message)}` : null,
    `抓取时间：${esc(record.captured_at)}`,
    `状态：${esc(record.crawl_status)}`,
  ].filter(Boolean).join('<br>');
  return `<td class="date ${cell.tone}">
    <div class="price">${esc(price)}</div>
    <div class="sales">月销量 ${esc(record.sales_text || '—')}</div>
    <details><summary>详情</summary>${details}</details>
  </td>`;
}

function renderTable(data) {
  renderTabs(data.product_lines, data.selected_product_line_id);
  currentLineId = data.selected_product_line_id;
  if (!data.product_lines.length) {
    document.querySelector('#table').innerHTML = '<div class="empty">产品输入表中没有有效商品。</div>';
    return;
  }
  let html = '<table><thead><tr>' +
    '<th class="fixed c1">品牌</th>' +
    '<th class="fixed c2">尺寸</th>' +
    '<th class="fixed c3">ASIN</th>' +
    data.dates.map(day => `<th class="date">${esc(day)}</th>`).join('') +
    '</tr></thead><tbody>';
  for (const product of data.products) {
    html += `<tr class="${product.is_self ? 'mine' : ''}">
      <td class="fixed c1">${esc(product.brand || '')}${product.is_self ? ' <small>我方</small>' : ''}</td>
      <td class="fixed c2">${esc(product.size_normalized || product.size_raw || '')}</td>
      <td class="fixed c3"><a target="_blank" rel="noreferrer" href="https://www.amazon.com/dp/${esc(product.asin)}">${esc(product.asin)}</a></td>
      ${product.cells.map(renderCell).join('')}
    </tr>`;
  }
  document.querySelector('#table').innerHTML = html + '</tbody></table>';
}

async function loadTable() {
  const params = new URLSearchParams({range: currentRange});
  if (currentLineId != null) params.set('product_line_id', currentLineId);
  try {
    const response = await fetch(`/api/table?${params.toString()}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || '表格加载失败');
    renderTable(data);
    if (!data.status.running) setStatus(data.status.message === 'idle' ? '已同步产品输入表' : data.status.message);
  } catch (error) {
    setStatus(error.message, true);
    document.querySelector('#table').innerHTML = `<div class="empty error-text">${esc(error.message)}</div>`;
  }
}

function beginPolling() {
  clearInterval(pollingTimer);
  pollingTimer = setInterval(async () => {
    try {
      const status = await fetch('/api/status').then(response => response.json());
      const completed = (status.success || 0) + (status.partial || 0) + (status.failed || 0);
      const progress = status.total ? `完成 ${completed}/${status.total}` : '';
      setStatus([status.message, progress].filter(Boolean).join('；'), status.browser_status === 'connection_failed');
      if (!status.running) {
        clearInterval(pollingTimer);
        pollingTimer = null;
        await loadTable();
      }
    } catch (error) {
      clearInterval(pollingTimer);
      pollingTimer = null;
      setStatus('无法读取抓取状态', true);
    }
  }, 1000);
}

document.querySelectorAll('[data-range]').forEach(button => {
  button.onclick = () => {
    currentRange = button.dataset.range;
    document.querySelectorAll('[data-range]').forEach(item => item.classList.toggle('active', item === button));
    loadTable();
  };
});

document.querySelector('#crawl').onclick = async () => {
  const button = document.querySelector('#crawl');
  button.disabled = true;
  try {
    const response = await fetch('/api/crawl', {method: 'POST'});
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || '启动抓取失败');
    setStatus(`抓取已启动，共 ${data.total} 个 ASIN`);
    beginPolling();
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    button.disabled = false;
  }
};

loadTable();
