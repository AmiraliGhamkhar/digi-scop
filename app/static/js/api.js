(() => {
  'use strict';

  class APIError extends Error {
    constructor(message, status = 0, payload = null) {
      super(message);
      this.name = 'APIError';
      this.status = status;
      this.payload = payload;
    }
  }

  const buildURL = (path, params = {}) => {
    const url = new URL(path, window.location.origin);
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') {
        url.searchParams.set(key, String(value));
      }
    });
    return url.pathname + url.search;
  };

  const request = async (path, params = {}) => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch(buildURL(path, params), {
        headers: { Accept: 'application/json' },
        credentials: 'same-origin',
        signal: controller.signal,
      });
      let payload = null;
      try { payload = await response.json(); } catch (_) { /* handled below */ }
      if (!response.ok) {
        const detail = payload && payload.detail;
        const message = typeof detail === 'string' ? detail : `خطای سرویس (${response.status})`;
        throw new APIError(message, response.status, payload);
      }
      if (payload === null) throw new APIError('پاسخ سرویس قابل خواندن نیست.', response.status);
      return payload;
    } catch (error) {
      if (error.name === 'AbortError') throw new APIError('زمان انتظار برای دریافت داده به پایان رسید.');
      if (error instanceof APIError) throw error;
      throw new APIError('ارتباط با سرویس برقرار نشد.');
    } finally {
      window.clearTimeout(timer);
    }
  };

  window.DigiAPI = Object.freeze({
    APIError,
    dashboard: () => request('/api/dashboard'),
    categories: () => request('/api/categories'),
    rankings: (filters) => request('/api/rankings', filters),
    product: (id) => request(`/api/products/${encodeURIComponent(id)}`),
    collectionStatus: () => request('/api/collection/status'),
    exportURL: (filters) => buildURL('/api/export.csv', filters),
  });
})();
