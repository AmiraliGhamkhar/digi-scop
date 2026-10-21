(() => {
  'use strict';

  const api = window.DigiAPI;
  const state = {
    period: 'current', scope: 'global', categoryId: '', limit: 10,
    offset: 0, sort: 'rank', query: '', selectedId: null, requestSerial: 0,
  };
  // The export endpoint serves the whole result set up to its own maximum;
  // it must not inherit the page size of the table.
  const EXPORT_LIMIT = 50;
  const faNumber = new Intl.NumberFormat('fa-IR');
  const faDate = new Intl.DateTimeFormat('fa-IR', {
    year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
  const byId = (id) => document.getElementById(id);
  const make = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };
  const number = (value) => value === null || value === undefined ? '—' : faNumber.format(value);
  const date = (value) => {
    if (!value) return '—';
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? '—' : faDate.format(parsed);
  };
  const toman = (value) => value === null || value === undefined ? 'موجود نیست' : `${number(value)} تومان`;
  const percent = (value) => value === null || value === undefined ? '—' : `${number(value)}٪`;

  const safeDigikalaURL = (value) => {
    if (!value) return null;
    try {
      const parsed = new URL(value);
      return parsed.protocol === 'https:' && ['digikala.com', 'www.digikala.com'].includes(parsed.hostname) ? parsed.href : null;
    } catch (_) { return null; }
  };
  const safeImageURL = (value) => {
    if (!value) return null;
    try { const parsed = new URL(value); return parsed.protocol === 'https:' ? parsed.href : null; }
    catch (_) { return null; }
  };

  const showError = (message) => {
    const box = byId('global-error');
    box.textContent = message;
    box.classList.remove('hidden');
  };
  const clearError = () => byId('global-error').classList.add('hidden');

  const setHealth = (health) => {
    const dot = byId('health-dot');
    dot.className = `status-dot ${health || 'neutral'}`;
    const labels = {
      healthy: ['داده زنده', 'badge-healthy'], warning: ['آخرین دریافت ناقص', 'badge-warning'],
      stale: ['داده قدیمی است', 'badge-warning'], error: ['خطا در آخرین دریافت داده', 'badge-error'],
      no_data: ['در انتظار نخستین جمع‌آوری', 'badge-muted'],
    };
    const [label, badge] = labels[health] || labels.no_data;
    const freshness = byId('data-freshness');
    freshness.textContent = label;
    freshness.className = `badge ${badge}`;
  };

  const fillCoverageMetric = (key, coverage) => {
    byId(`metric-coverage-${key}`).textContent = `${number(coverage.coverage_percent)}٪`;
    byId(`metric-coverage-${key}-note`).textContent = `${number(coverage.successful_runs)} از ${number(coverage.expected_runs)} اجرای مورد انتظار`;
  };

  const renderDashboard = (data) => {
    byId('last-collected').textContent = date(data.latest_successful_collection_at);
    byId('metric-products').textContent = number(data.monitored_products);
    byId('metric-observations').textContent = number(data.ranking_observations);
    fillCoverageMetric('7', data.coverage['7d']);
    fillCoverageMetric('30', data.coverage['30d']);
    setHealth(data.collection_health);
    byId('demo-banner').classList.toggle('hidden', !data.demo_data);
  };

  const flattenCategories = (categories, depth = 0, result = []) => {
    categories.forEach((category) => {
      result.push({ ...category, depth });
      flattenCategories(category.children || [], depth + 1, result);
    });
    return result;
  };

  const renderCategories = (categories) => {
    const select = byId('category-select');
    const placeholder = make('option', '', categories.length ? 'انتخاب دسته' : 'دسته‌ای ثبت نشده');
    placeholder.value = '';
    select.replaceChildren(placeholder);
    flattenCategories(categories).forEach((category) => {
      const option = make('option', '', `${'— '.repeat(category.depth)}${category.title}`);
      option.value = String(category.id);
      select.append(option);
    });
    select.disabled = state.scope !== 'category' || categories.length === 0;
  };

  const rankingParams = () => ({
    period: state.period,
    scope: state.scope,
    category_id: state.scope === 'category' ? state.categoryId : undefined,
    limit: state.limit,
    offset: state.offset,
    sort: state.sort,
    q: state.query || undefined,
  });

  const updateExport = () => {
    const params = rankingParams();
    delete params.offset;
    params.limit = EXPORT_LIMIT;
    byId('export-link').href = api.exportURL(params);
  };

  const loadingTable = () => {
    const cell = make('td'); cell.colSpan = 10;
    const wrapper = make('div', 'loading-state');
    wrapper.append(make('span', 'spinner'), document.createTextNode(' در حال دریافت داده…'));
    cell.append(wrapper);
    const row = make('tr'); row.append(cell);
    byId('products-body').replaceChildren(row);
  };

  const messageTable = (message, isError = false) => {
    const cell = make('td'); cell.colSpan = 10;
    cell.append(make('div', isError ? 'error-table' : 'empty-table', message));
    const row = make('tr'); row.append(cell);
    byId('products-body').replaceChildren(row);
  };

  const changeNode = (value, sufficient) => {
    if (!sufficient || value === null || value === undefined) return make('span', 'na', '—');
    if (value > 0) return make('span', 'change up', `↑ ${number(value)}`);
    if (value < 0) return make('span', 'change down', `↓ ${number(Math.abs(value))}`);
    return make('span', 'change same', 'بدون تغییر');
  };

  const productCell = (item) => {
    const wrapper = make('div', 'product-cell');
    const avatar = make('span', 'product-avatar', (item.title || 'ک').trim().charAt(0));
    const imageURL = safeImageURL(item.image_url);
    if (imageURL) {
      const image = document.createElement('img');
      image.src = imageURL; image.alt = ''; image.loading = 'lazy'; image.referrerPolicy = 'no-referrer';
      image.addEventListener('error', () => { image.remove(); avatar.textContent = (item.title || 'ک').trim().charAt(0); }, { once: true });
      avatar.replaceChildren(image);
    }
    const text = make('span');
    text.append(make('strong', '', item.title), make('small', '', `DKP ${item.external_id}`));
    wrapper.append(avatar, text);
    return wrapper;
  };

  const renderTable = (result) => {
    const body = byId('products-body');
    const rows = result.items.map((item) => {
      const row = make('tr', `data-row${state.selectedId === item.id ? ' selected' : ''}`);
      row.tabIndex = 0;
      row.setAttribute('aria-label', `نمایش جزئیات ${item.title}`);
      const values = [
        make('span', 'rank-cell', number(item.current_rank)),
        productCell(item),
        make('span', 'price-cell', toman(item.price_toman)),
        item.discount_percent ? make('span', 'discount', percent(item.discount_percent)) : make('span', 'na', '—'),
      ];
      const rating = item.rating_stars === null ? make('span', 'na', '—') : make('span', 'rating', `★ ${number(item.rating_stars)} (${number(item.rating_count)})`);
      const content = [values[0], values[1], values[2], values[3], rating,
        make('span', 'rank-cell', number(item.current_rank)),
        changeNode(item.rank_change, item.sufficient_history),
        make('span', '', number(item.observation_count)),
        make('span', 'muted', date(item.last_observed)),
      ];
      content.forEach((node) => { const cell = make('td'); cell.append(node); row.append(cell); });
      const linkCell = make('td');
      const url = safeDigikalaURL(item.url);
      if (url) {
        const link = make('a', 'external-link', '↗'); link.href = url; link.target = '_blank';
        link.rel = 'noopener noreferrer'; link.setAttribute('aria-label', 'مشاهده محصول در دیجی‌کالا');
        link.addEventListener('click', (event) => event.stopPropagation()); linkCell.append(link);
      } else linkCell.append(make('span', 'na', '—'));
      row.append(linkCell);
      const choose = () => selectProduct(item.id, row);
      row.addEventListener('click', choose);
      row.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); choose(); } });
      return row;
    });
    if (rows.length) body.replaceChildren(...rows);
    else messageTable('در این محدوده، مشاهده‌ای ثبت نشده است. داده‌های گمشده با داده فعلی پر نمی‌شوند.');

    const total = result.pagination.total;
    const currentPage = Math.floor(result.pagination.offset / result.pagination.limit) + 1;
    const pages = Math.max(1, Math.ceil(total / result.pagination.limit));
    byId('table-count').textContent = `${number(total)} مورد`;
    byId('page-label').textContent = `صفحه ${number(currentPage)} از ${number(pages)}`;
    byId('prev-page').disabled = result.pagination.offset === 0;
    byId('next-page').disabled = result.pagination.offset + result.pagination.limit >= total;
    byId('table-updated').textContent = result.observed_at ? `آخرین مشاهده: ${date(result.observed_at)}` : 'بدون مشاهده موفق';
    byId('table-title').textContent = state.period === 'current' ? 'محصولات برتر فعلی' : `گزارش ثبت‌شده ${state.period === '7d' ? '۷ روزه' : '۳۰ روزه'}`;
    renderCoverage(result.coverage);
    updateExport();
  };

  const renderCoverage = (coverage) => {
    const strip = byId('coverage-notice');
    const dot = strip.querySelector('.status-dot');
    const strong = strip.querySelector('strong');
    const description = strip.querySelector('span:last-child');
    if (!coverage) {
      dot.className = 'status-dot healthy'; strong.textContent = 'داده زنده';
      description.textContent = 'رتبه فعلی، همان جایگاه مشاهده‌شده در آخرین اجرای موفق است.';
      return;
    }
    dot.className = `status-dot ${coverage.complete ? 'healthy' : 'warning'}`;
    strong.textContent = coverage.label;
    description.textContent = `پوشش ${number(coverage.coverage_percent)}٪؛ ${number(coverage.successful_runs)} اجرای موفق از ${number(coverage.expected_runs)} فرصت مورد انتظار. ${number(coverage.failed_runs_excluded)} اجرای ناموفق، غیبت محصول محاسبه نشده است.`;
  };

  const loadRankings = async () => {
    if (state.scope === 'category' && !state.categoryId) {
      messageTable('برای مشاهده رتبه‌بندی، یک دسته را انتخاب کنید.');
      return;
    }
    const serial = ++state.requestSerial;
    loadingTable(); clearError();
    try {
      const result = await api.rankings(rankingParams());
      if (serial !== state.requestSerial) return;
      renderTable(result);
      if (result.items.length && !state.selectedId) selectProduct(result.items[0].id, bodyRowFor(result.items[0].id));
    } catch (error) {
      if (serial !== state.requestSerial) return;
      messageTable(error.message, true);
    }
  };

  const bodyRowFor = (id) => [...byId('products-body').querySelectorAll('tr.data-row')].find((row) => row.getAttribute('aria-label')) || null;

  const selectProduct = async (id, row) => {
    state.selectedId = id;
    byId('products-body').querySelectorAll('tr').forEach((candidate) => candidate.classList.remove('selected'));
    if (row) row.classList.add('selected');
    byId('detail-empty').classList.add('hidden');
    byId('detail-content').classList.add('hidden');
    try {
      const detail = await api.product(id);
      if (state.selectedId !== id) return;
      renderDetail(detail);
    } catch (error) {
      showError(`جزئیات محصول دریافت نشد: ${error.message}`);
    }
  };

  const renderDetail = (detail) => {
    byId('detail-content').classList.remove('hidden');
    byId('detail-title').textContent = detail.title;
    byId('detail-id').textContent = `شناسه منبع: ${detail.external_id} · روش هویت: ${detail.identity_source}`;
    byId('detail-image-fallback').textContent = detail.title.trim().charAt(0);
    byId('detail-price').textContent = toman(detail.latest_snapshot && detail.latest_snapshot.price_toman);
    byId('detail-first').textContent = date(detail.first_seen_at);
    byId('detail-last').textContent = date(detail.last_seen_at);
    byId('detail-rank-count').textContent = number(detail.ranking_history.length);
    const link = byId('product-external-link');
    const safeURL = safeDigikalaURL(detail.url);
    link.classList.toggle('hidden', !safeURL);
    if (safeURL) link.href = safeURL;

    const coverageBox = byId('detail-coverage');
    const chips = [];
    Object.entries(detail.coverage || {}).forEach(([scope, periods]) => {
      Object.entries(periods).forEach(([period, coverage]) => {
        const chip = make('span', 'coverage-chip');
        chip.append(document.createTextNode(`${scope === 'global' ? 'کل بازار' : 'دسته'} · ${period === '7d' ? '۷ روز' : '۳۰ روز'} `));
        chip.append(make('b', '', `${number(coverage.coverage_percent)}٪ — ${coverage.label}`));
        chips.push(chip);
      });
    });
    coverageBox.replaceChildren(...(chips.length ? chips : [make('span', 'coverage-chip', 'داده کافی برای محاسبه پوشش وجود ندارد') ]));
    window.DigiCharts.updateRank(detail.ranking_history);
    window.DigiCharts.updatePrice(detail.price_history);
  };

  const renderCollection = (data) => {
    const box = byId('collection-list');
    if (!data.runs.length) {
      box.replaceChildren(make('div', 'empty-state', 'هنوز اجرای جمع‌آوری ثبت نشده است.'));
      return;
    }
    const statusLabel = { success: 'موفق', partial: 'ناقص', failed: 'ناموفق', running: 'در حال اجرا' };
    const rows = data.runs.slice(0, 8).map((run) => {
      const row = make('div', 'run-row');
      row.append(make('span', `run-status ${run.status}`, statusLabel[run.status] || run.status));
      const main = make('div', 'run-main');
      main.append(make('strong', '', run.scope_key === 'global' ? 'کل بازار' : `دسته ${run.category_id}`), make('small', '', `${run.sort_type} · اجرای ${number(run.id)}`));
      row.append(main, make('span', 'run-count', `${number(run.items_saved)} مشاهده`), make('time', 'run-time', date(run.started_at)));
      if (run.error_message) row.append(make('p', 'run-error', run.error_message));
      return row;
    });
    box.replaceChildren(...rows);
  };

  const refreshSummary = async () => {
    clearError();
    const [dashboard, categories, collection] = await Promise.allSettled([
      api.dashboard(), api.categories(), api.collectionStatus(),
    ]);
    if (dashboard.status === 'fulfilled') renderDashboard(dashboard.value);
    else showError(`نمای کلی دریافت نشد: ${dashboard.reason.message}`);
    if (categories.status === 'fulfilled') renderCategories(categories.value);
    else showError(`فهرست دسته‌ها دریافت نشد: ${categories.reason.message}`);
    if (collection.status === 'fulfilled') renderCollection(collection.value);
    else byId('collection-list').replaceChildren(make('div', 'error-table', collection.reason.message));
  };

  const bindControls = () => {
    document.querySelectorAll('.period-button').forEach((button) => button.addEventListener('click', () => {
      document.querySelectorAll('.period-button').forEach((item) => item.classList.remove('active'));
      button.classList.add('active'); state.period = button.dataset.period; state.offset = 0; loadRankings();
    }));
    byId('scope-select').addEventListener('change', (event) => {
      state.scope = event.target.value; state.offset = 0;
      const categoryMode = state.scope === 'category';
      byId('category-label').classList.toggle('hidden', !categoryMode);
      byId('category-select').disabled = !categoryMode;
      loadRankings();
    });
    byId('category-select').addEventListener('change', (event) => { state.categoryId = event.target.value; state.offset = 0; loadRankings(); });
    byId('limit-select').addEventListener('change', (event) => { state.limit = Number(event.target.value); state.offset = 0; loadRankings(); });
    byId('sort-select').addEventListener('change', (event) => { state.sort = event.target.value; state.offset = 0; loadRankings(); });
    let searchTimer;
    byId('search-input').addEventListener('input', (event) => {
      window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(() => { state.query = event.target.value.trim(); state.offset = 0; loadRankings(); }, 300);
    });
    byId('next-page').addEventListener('click', () => { state.offset += state.limit; loadRankings(); });
    byId('prev-page').addEventListener('click', () => { state.offset = Math.max(0, state.offset - state.limit); loadRankings(); });
    byId('refresh-button').addEventListener('click', async () => { await refreshSummary(); await loadRankings(); });
    byId('menu-button').addEventListener('click', (event) => {
      const open = document.body.classList.toggle('menu-open'); event.currentTarget.setAttribute('aria-expanded', String(open));
    });
    document.querySelectorAll('.nav-link').forEach((link) => link.addEventListener('click', () => document.body.classList.remove('menu-open')));
  };

  document.addEventListener('DOMContentLoaded', async () => {
    bindControls();
    await refreshSummary();
    await loadRankings();
  });
})();
