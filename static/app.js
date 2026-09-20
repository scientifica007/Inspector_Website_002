document.querySelectorAll('[data-record-form]').forEach(form => {
  form.addEventListener('input', () => {
    form.dataset.dirty = '1';
    form.querySelector('.save-state').textContent = 'تغييرات غير محفوظة';
  });
  form.addEventListener('submit', () => { delete form.dataset.dirty; });
});
window.addEventListener('beforeunload', event => {
  if (document.querySelector('[data-dirty="1"]')) {
    event.preventDefault();
    event.returnValue = '';
  }
});

// Optional read-only agent access to the same visible working surface.
if (document.modelContext?.registerTool) {
  const lifecycle = new AbortController();
  Promise.resolve(document.modelContext.registerTool({
    name: 'read_visible_inspection',
    title: 'قراءة مساحة التفتيش المعروضة',
    description: 'Read the visible visit heading, progress and inspection items. Does not save or change any data.',
    inputSchema: {type: 'object', properties: {}, additionalProperties: false},
    annotations: {readOnlyHint: true, untrustedContentHint: true},
    execute(input) {
      if (!input || Array.isArray(input) || typeof input !== 'object' || Object.keys(input).length) {
        throw new Error('Expected an empty object.');
      }
      return {
        heading: document.querySelector('h1')?.textContent.trim() || '',
        progress: document.querySelector('.visit-progress')?.textContent.trim() || null,
        items: Array.from(document.querySelectorAll('.execution-card')).map(card => ({
          title: card.querySelector('h3')?.textContent.trim(),
          labels: Array.from(card.querySelectorAll('.badge')).map(badge => badge.textContent.trim())
        }))
      };
    }
  }, {signal: lifecycle.signal})).catch(() => {});
  window.addEventListener('pagehide', () => lifecycle.abort(), {once: true});
}
