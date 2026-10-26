'use strict';

const $ = selector => document.querySelector(selector);
const state = { jobs: [], token: '', mode: 'direct', online: false, config: null,
  view: 'download', analyzing: false, polling: false, batchDownloading: false, selections: {}, renderKey: '', busy: new Set() };
const statuses = { queued_analyze: 'Chờ phân tích', analyzing: 'Đang đọc thông tin video',
  ready: 'Sẵn sàng tải', queued_download: 'Đang chờ lượt tải', downloading: 'Đang tải video',
  processing: 'Đang ghép / xử lý tệp', completed: 'Đã tải hoàn tất', error: 'Chưa tải được', cancelled: 'Đã hủy' };
const activeStatuses = new Set(['queued_analyze', 'analyzing', 'queued_download', 'downloading', 'processing']);
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const icon = name => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
const formatSize = value => { if (!value) return ''; const unit = value >= 1073741824 ? 1073741824 : value >= 1048576 ? 1048576 : 1024; return `${(value / unit).toFixed(unit === 1024 ? 0 : 1)} ${unit === 1073741824 ? 'GB' : unit === 1048576 ? 'MB' : 'KB'}`; };
const duration = value => { if (!Number.isFinite(value)) return ''; const seconds = Math.floor(value); return seconds >= 3600 ? `${Math.floor(seconds / 3600)}:${String(Math.floor(seconds % 3600 / 60)).padStart(2,'0')}:${String(seconds % 60).padStart(2,'0')}` : `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2,'0')}`; };
const qualityLabel = item => `${item.height >= 2160 ? `${item.height === 2160 ? '4K' : item.height >= 4320 ? '8K' : item.height + 'p'} · ` : ''}${item.height ? item.height + 'p' : 'Gốc'}${item.fps ? ' · ' + item.fps + 'fps' : ''} · ${(item.ext || '').toUpperCase()}`;

function toast(message, error = false) {
  const element = document.createElement('div');
  element.className = `toast${error ? ' error' : ''}`;
  element.textContent = message;
  $('#toasts').append(element);
  setTimeout(() => element.remove(), error ? 8000 : 4500);
}

function endpoint(action) {
  return state.mode === 'php' ? `api.php?action=${encodeURIComponent(action)}` : `api/${action}`;
}

async function api(action, body) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 35000);
  try {
    const response = await fetch(endpoint(action), {
      method: body ? 'POST' : 'GET', cache: 'no-store', signal: controller.signal,
      headers: body ? { 'Content-Type': 'application/json', 'X-DownVideo-Token': state.token } : {},
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    let data;
    try { data = await response.json(); } catch { throw new Error('Máy chủ trả về dữ liệu không hợp lệ.'); }
    if (!response.ok) throw new Error(data.error || 'Không thể xử lý yêu cầu.');
    return data;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('Yêu cầu quá lâu. Kiểm tra kết nối rồi thử lại.');
    throw error;
  } finally { clearTimeout(timeout); }
}

function setConnection(online) {
  state.online = online;
  $('#connection').className = `connection ${online ? 'online' : 'offline'}`;
  $('#connection span').textContent = online ? 'Sẵn sàng tải' : 'Chưa kết nối máy chủ';
  $('#analyze-button').disabled = !online || state.analyzing;
}

async function connect() {
  for (const mode of ['direct', 'php']) {
    state.mode = mode;
    try {
      const config = await api('config');
      if (!config.token) continue;
      state.config = config;
      state.token = config.token;
      setConnection(config.engine_ready && config.ffmpeg_ready);
      if (config.hosted) renderHostedCopy(config);
      renderSystem();
      await poll();
      return;
    } catch { /* A XAMPP page uses the local PHP bridge. */ }
  }
  setConnection(false);
  renderSystem();
}

function renderSystem() {
  const config = state.config;
  $('#system-info').innerHTML = [
    ['Máy chủ tải video', state.online], ['yt-dlp', config?.engine_ready],
    ['FFmpeg', config?.ffmpeg_ready], ['Deno · hỗ trợ YouTube', config?.runtime_ready],
  ].map(([name, ready]) => `<div><span>${name}</span><span class="${ready ? '' : 'missing'}">${ready ? '✓ Sẵn sàng' : 'Chưa sẵn sàng'}</span></div>`).join('');
}

function renderHostedCopy(config) {
  const hours = Number(config.retention_hours) || 24;
  $('#settings-button small').textContent = 'Video lưu tạm trên máy chủ';
  $('#view-history .page-intro p').textContent = `Những lượt tải hoàn tất, được giữ trên máy chủ trong ${hours} giờ.`;
  $('#settings-dialog h2').textContent = 'Không gian tải riêng của bạn.';
  $('#settings-dialog .dialog-description').textContent = 'Các tùy chọn chất lượng được ghi nhớ trên trình duyệt. Video được xử lý trên máy chủ. Bấm Lưu về máy để giữ bản riêng trên thiết bị của bạn.';
  $('#settings-dialog .dialog-note').textContent = `Tệp và lịch sử được tự động dọn sau ${hours} giờ. Các thiết bị dùng chung tài khoản truy cập sẽ thấy cùng hàng đợi và lịch sử.`;
}

function getOptions() {
  return { quality: $('#quality-select').value, fps: $('#fps-select').value, container: $('#container-select').value };
}

function loadSettings() {
  try {
    const settings = JSON.parse(localStorage.getItem('downvideo.settings') || '{}');
    for (const key of ['quality', 'fps', 'container']) {
      const select = $(`#${key}-select`);
      if ([...select.options].some(option => option.value === settings[key])) select.value = settings[key];
    }
  } catch { /* Browser storage is optional. */ }
}

function saveSettings() {
  try { localStorage.setItem('downvideo.settings', JSON.stringify(getOptions())); } catch { /* Optional. */ }
}

function inputLinks() {
  return [...new Set($('#url-input').value.trim().split(/\s+/).filter(Boolean))];
}

function countLinks() {
  const count = inputLinks().length;
  $('#link-count').textContent = `${count} liên kết`;
}

function updateJob(job) {
  const index = state.jobs.findIndex(item => item.id === job.id);
  if (index >= 0) state.jobs[index] = job;
  else state.jobs.unshift(job);
  state.renderKey = '';
  render();
}

async function analyzeLinks() {
  const links = inputLinks();
  if (!links.length) { $('#url-input').focus(); return toast('Dán ít nhất một link video để bắt đầu.', true); }
  if (links.length > 100) return toast('Mỗi lần thêm tối đa 100 link. Hãy chia danh sách thành nhiều lượt.', true);
  const invalid = links.filter(link => { try { return !['http:', 'https:'].includes(new URL(link).protocol); } catch { return true; } });
  if (invalid.length) return toast(`${invalid.length} liên kết không hợp lệ. Mỗi link cần bắt đầu bằng http:// hoặc https://.`, true);
  if (!state.online) return toast(state.config?.hosted ? 'Máy chủ đang chưa sẵn sàng. Hãy thử lại sau ít phút.' : 'Hãy chạy start.bat trong thư mục DownVideo để kết nối máy chủ.', true);
  state.analyzing = true;
  $('#analyze-button').disabled = true;
  $('#analyze-button span').textContent = 'Đang thêm liên kết…';
  $('#batch-status').hidden = false;
  let added = 0, skipped = 0;
  const failed = [];
  for (let index = 0; index < links.length; index++) {
    $('#batch-status').textContent = `Đang thêm liên kết ${index + 1}/${links.length}. Có thể xử lý tối đa ${state.config?.max_active || 3} video cùng lúc.`;
    if (state.jobs.some(job => job.url === links[index] && (activeStatuses.has(job.status) || job.status === 'ready'))) { skipped++; continue; }
    try { const result = await api('analyze', { url: links[index] }); updateJob(result.job); added++; }
    catch (error) { failed.push(links[index]); toast(error.message, true); }
  }
  $('#url-input').value = failed.join('\n');
  countLinks();
  $('#batch-status').hidden = true;
  state.analyzing = false;
  $('#analyze-button').disabled = !state.online;
  $('#analyze-button span').textContent = 'Phân tích liên kết';
  if (added) toast(`Đã thêm ${added} video vào hàng đợi phân tích.${skipped ? ` Bỏ qua ${skipped} link đã có.` : ''}`);
  else if (skipped) toast('Các link này đã có trong hàng đợi.');
  await poll();
}

async function poll() {
  if (!state.token || state.polling) return;
  state.polling = true;
  try {
    const data = await api('jobs');
    state.jobs = data.jobs;
    setConnection(Boolean(state.config?.engine_ready && state.config?.ffmpeg_ready));
    render();
  } catch { setConnection(false); }
  finally { state.polling = false; }
}

function renderJob(job) {
  const running = activeStatuses.has(job.status);
  const loading = ['analyzing', 'downloading', 'processing'].includes(job.status);
  const title = job.title || (job.status === 'queued_analyze' ? 'Đang chờ đọc thông tin video…' : 'Đang đọc thông tin video…');
  let hostname = '';
  try { hostname = new URL(job.url).hostname.replace(/^www\./, ''); } catch { /* Old record. */ }
  const source = job.source || hostname;
  let image = '';
  try { if (['http:', 'https:'].includes(new URL(job.thumbnail).protocol)) image = `<img src="${escapeHTML(job.thumbnail)}" alt="" loading="lazy" referrerpolicy="no-referrer">`; } catch { /* Use icon. */ }
  const formats = job.formats || [];
  const best = formats[0];
  const actual = job.actual_height ? `${job.actual_height}p${job.actual_fps ? ' · ' + job.actual_fps + 'fps' : ''}` : best ? `${best.height ? best.height + 'p' : 'Độ phân giải gốc'}${best.fps ? ' · ' + best.fps + 'fps' : ''}` : '';
  const meta = [source, actual, job.size ? formatSize(job.size) : job.uploader].filter(Boolean);
  let actions = '';
  if (job.status === 'ready') {
    const selection = state.selections[job.id] || 'best';
    actions = `<select class="job-quality" data-id="${job.id}" aria-label="Chất lượng cho ${escapeHTML(job.title)}"><option value="best">Theo tùy chọn ở trên</option>${formats.map(item => `<option value="${item.key}" ${item.key === selection ? 'selected' : ''}>${escapeHTML(qualityLabel(item))}</option>`).join('')}</select><button class="primary-button job-button" data-action="download" data-id="${job.id}" ${state.busy.has(job.id) ? 'disabled' : ''}>${icon('download')}Tải video</button>`;
  } else if (running) {
    actions = `<button class="icon-button" data-action="cancel" data-id="${job.id}" aria-label="Hủy tác vụ" title="Hủy tác vụ">${icon('close')}</button>`;
  } else if (job.status === 'completed') {
    actions = `<a class="primary-button job-button" href="${escapeHTML(endpoint('file/' + job.id))}" download>${icon('download')}Lưu về máy</a>`;
  } else {
    actions = `<button class="subtle-button job-button" style="margin:0" data-action="retry" data-id="${job.id}">${icon('refresh')}Thử lại</button>`;
  }
  if (!running) actions += `<button class="icon-button" data-action="remove" data-id="${job.id}" aria-label="Ẩn khỏi danh sách" title="Ẩn khỏi danh sách; tệp vẫn được giữ đến khi hết hạn lưu trữ">${icon('close')}</button>`;
  const progress = Math.max(0, Math.min(100, Number(job.progress) || 0));
  const progressMarkup = loading ? `<div class="progress-track" role="progressbar" aria-label="Tiến trình tải" aria-valuenow="${Math.round(progress)}" aria-valuemin="0" aria-valuemax="100"><div class="progress-fill${job.status === 'analyzing' || !progress ? ' indeterminate' : ''}" style="width:${progress}%"></div></div>${job.status === 'downloading' ? `<div class="job-speed"><span>${progress ? progress.toFixed(0) + '%' : 'Đang kết nối nguồn'}${job.speed ? ' · ' + formatSize(job.speed) + '/s' : ''}</span><span>${job.eta ? 'Còn ' + duration(job.eta) : ''}</span></div>` : ''}` : '';
  const fallback = job.title || 'Video từ ' + hostname;
  return `<article class="job-card" data-job="${job.id}"><div class="job-thumb">${icon('play')}${image}${job.duration ? `<span class="duration">${duration(job.duration)}</span>` : ''}</div><div class="job-info"><h3 title="${escapeHTML(job.url)}">${escapeHTML(job.status === 'error' || job.status === 'cancelled' ? fallback : title)}</h3><div class="job-meta">${meta.map(item => `<span>${escapeHTML(item)}</span>`).join('')}</div><div class="job-status ${job.status}" role="status">${loading ? '<span class="busy-spinner"></span>' : job.status === 'completed' ? '✓ ' : ''}${statuses[job.status] || escapeHTML(job.status)}</div>${job.error ? `<p class="job-error">${escapeHTML(job.error)}</p>` : ''}${progressMarkup}${job.has_audio === false && formats.length ? '<span class="job-status">Nguồn không cung cấp âm thanh</span>' : ''}</div><div class="job-actions">${actions}</div></article>`;
}

function render() {
  const key = JSON.stringify([state.jobs, state.selections, [...state.busy], state.online, state.batchDownloading, $('#history-search').value]);
  if (key === state.renderKey) return;
  // Keep an open quality dropdown stable while other jobs report their progress.
  if (document.activeElement?.classList.contains('job-quality')) return;
  state.renderKey = key;
  const queue = state.jobs.filter(job => job.status !== 'completed');
  const history = state.jobs.filter(job => job.status === 'completed');
  const query = $('#history-search').value.trim().toLocaleLowerCase('vi');
  const filtered = history.filter(job => (job.title || '').toLocaleLowerCase('vi').includes(query));
  $('#queue-count').textContent = queue.length;
  $('#history-count').textContent = history.length;
  $('#queue-list').innerHTML = queue.map(renderJob).join('');
  $('#history-list').innerHTML = filtered.map(renderJob).join('');
  $('#queue-empty').hidden = queue.length > 0;
  $('#history-empty').hidden = filtered.length > 0;
  $('#history-empty h3').textContent = query && history.length ? 'Không tìm thấy video phù hợp' : 'Chưa có video nào được tải';
  $('#history-empty p').textContent = query && history.length ? 'Thử một từ khóa khác để tìm video.' : 'Video hoàn tất sẽ được lưu vào lịch sử tại đây.';
  $('#download-all').disabled = !queue.some(job => job.status === 'ready') || !state.online || state.batchDownloading;
}

async function downloadJob(job) {
  const result = await api('download', { id: job.id, selection: state.selections[job.id] || 'best', ...getOptions() });
  updateJob(result.job);
}

async function handleAction(event) {
  const button = event.target.closest('[data-action]');
  if (!button) return;
  const job = state.jobs.find(item => item.id === button.dataset.id);
  if (!job || state.busy.has(job.id)) return;
  state.busy.add(job.id);
  button.disabled = true;
  try {
    if (button.dataset.action === 'download') await downloadJob(job);
    if (button.dataset.action === 'cancel') { const data = await api('cancel', {id: job.id}); updateJob(data.job); toast('Đã hủy tác vụ.'); }
    if (button.dataset.action === 'remove') { await api('remove', {id: job.id}); state.jobs = state.jobs.filter(item => item.id !== job.id); render(); }
    if (button.dataset.action === 'retry') {
      if (job.formats?.length) await downloadJob(job);
      else {
        const result = await api('analyze', { url: job.url });
        updateJob(result.job);
        await api('remove', {id: job.id});
        state.jobs = state.jobs.filter(item => item.id !== job.id);
      }
    }
  } catch (error) { toast(error.message, true); }
  finally { state.busy.delete(job.id); state.renderKey = ''; render(); }
}

async function downloadAll() {
  if (state.batchDownloading) return;
  state.batchDownloading = true;
  const ready = state.jobs.filter(job => job.status === 'ready' && !state.busy.has(job.id));
  $('#download-all').disabled = true;
  let added = 0;
  for (const job of ready) {
    state.busy.add(job.id);
    try { await downloadJob(job); added++; } catch (error) { toast(error.message, true); }
    finally { state.busy.delete(job.id); }
  }
  state.renderKey = '';
  state.batchDownloading = false;
  render();
  if (added) toast(`Đã đưa ${added} video vào hàng đợi tải.`);
}

function switchView() {
  const view = location.hash.slice(1);
  state.view = ['download', 'history', 'sources'].includes(view) ? view : 'download';
  for (const section of document.querySelectorAll('.view')) section.hidden = section.id !== `view-${state.view}`;
  for (const link of document.querySelectorAll('[data-view]')) {
    const active = link.dataset.view === state.view;
    link.classList.toggle('active', active);
    if (active) link.setAttribute('aria-current','page'); else link.removeAttribute('aria-current');
  }
  $('#page-crumb').textContent = {download: 'Tải video', history: 'Lịch sử tải', sources: 'Nguồn hỗ trợ'}[state.view];
  $('#sidebar').classList.remove('open');
  window.scrollTo({top:0, behavior:'instant'});
}

async function importFile(file) {
  if (!file || !/\.txt$/i.test(file.name)) return toast('Hãy chọn tệp .txt chứa mỗi liên kết trên một dòng.', true);
  if (file.size > 1024 * 1024) return toast('Tệp quá lớn. Vui lòng dùng tệp .txt nhỏ hơn 1 MB.', true);
  try {
    const text = await file.text();
    $('#url-input').value += ($('#url-input').value.trim() ? '\n' : '') + text;
    countLinks();
    toast('Đã nhập liên kết. Bấm Phân tích liên kết để tiếp tục.');
  } catch { toast('Không đọc được tệp. Vui lòng thử lại.', true); }
  $('#file-input').value = '';
}

function buildSources() {
  const sources = [
    ['▶','YouTube','Video, Shorts và các chất lượng được nguồn cung cấp.','Video & Shorts'],
    ['♪','TikTok','Dán liên kết video công khai từ TikTok.','Video ngắn'],
    ['f','Facebook','Video và Reels công khai, khi nguồn cho phép truy cập.','Video & Reels'],
    ['◎','Instagram','Video và Reels công khai. Một số link yêu cầu đăng nhập.','Video & Reels'],
    ['𝕏','X / Twitter','Video được đính kèm trong bài đăng công khai.','Video trong bài đăng'],
    ['↗','Và nhiều nguồn khác','Vimeo, Dailymotion, Twitch, Bilibili và link tệp video trực tiếp.','Tùy hỗ trợ của nguồn'],
  ];
  $('#source-grid').innerHTML = sources.map(([mark,title,text,tag]) => `<article class="source-card"><span aria-hidden="true">${mark}</span><h3>${title}</h3><p>${text}</p><div class="source-tag">${tag}</div></article>`).join('');
}

function bindEvents() {
  $('#url-input').addEventListener('input', countLinks);
  $('#analyze-button').addEventListener('click', analyzeLinks);
  $('#url-input').addEventListener('keydown', event => { if ((event.ctrlKey || event.metaKey) && event.key === 'Enter' && !state.analyzing) { event.preventDefault(); analyzeLinks(); } });
  $('#paste-button').addEventListener('click', async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (!text.trim()) return toast('Bộ nhớ tạm chưa có liên kết.', true);
      $('#url-input').value += ($('#url-input').value.trim() ? '\n' : '') + text.trim();
      countLinks(); $('#url-input').focus();
    } catch { $('#url-input').focus(); toast('Bấm Ctrl + V để dán link vào ô nhập.'); }
  });
  $('#import-button').addEventListener('click', () => $('#file-input').click());
  $('#file-input').addEventListener('change', event => importFile(event.target.files[0]));
  $('#drop-zone').addEventListener('dragover', event => { event.preventDefault(); $('#drop-zone').classList.add('dragging'); });
  $('#drop-zone').addEventListener('dragleave', event => { if (!$('#drop-zone').contains(event.relatedTarget)) $('#drop-zone').classList.remove('dragging'); });
  $('#drop-zone').addEventListener('drop', event => { event.preventDefault(); $('#drop-zone').classList.remove('dragging'); importFile(event.dataTransfer.files[0]); });
  for (const key of ['quality','fps','container']) $(`#${key}-select`).addEventListener('change', saveSettings);
  $('#download-all').addEventListener('click', downloadAll);
  for (const list of [$('#queue-list'), $('#history-list')]) {
    list.addEventListener('click', handleAction);
    list.addEventListener('change', event => { if (event.target.matches('.job-quality')) state.selections[event.target.dataset.id] = event.target.value; });
    list.addEventListener('error', event => { if (event.target.tagName === 'IMG') event.target.remove(); }, true);
  }
  $('#history-search').addEventListener('input', render);
  $('#more-sources').addEventListener('click', () => { location.hash = 'sources'; });
  const openHelp = () => $('#help-dialog').showModal();
  $('#help-button').addEventListener('click', openHelp);
  $('#top-help').addEventListener('click', openHelp);
  $('#settings-button').addEventListener('click', () => { renderSystem(); $('#settings-dialog').showModal(); });
  document.querySelectorAll('.close-dialog').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
  document.querySelectorAll('dialog').forEach(dialog => dialog.addEventListener('click', event => { if (event.target === dialog) { const box = dialog.getBoundingClientRect(); if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dialog.close(); } }));
  $('#reset-settings').addEventListener('click', () => { $('#quality-select').value = 'best'; $('#fps-select').value = 'original'; $('#container-select').value = 'auto'; saveSettings(); toast('Đã khôi phục tùy chọn chất lượng gốc.'); });
  $('#menu-button').addEventListener('click', () => $('#sidebar').classList.toggle('open'));
  document.addEventListener('click', event => { if (!event.target.closest('#sidebar, #menu-button')) $('#sidebar').classList.remove('open'); });
  window.addEventListener('hashchange', switchView);
  window.addEventListener('online', connect);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) state.online ? poll() : connect(); });
}

loadSettings();
buildSources();
bindEvents();
switchView();
countLinks();
connect();
setInterval(() => { if (!document.hidden) state.online ? poll() : connect(); }, 2000);

