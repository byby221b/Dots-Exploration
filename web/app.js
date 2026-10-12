'use strict';
(function () {
  const form = document.querySelector('.filters');
  if (!form) return;
  const fields = ['q', 'series', 'from', 'to'];
  const inputs = Object.fromEntries(fields.map(k => [k, document.getElementById(k)]));
  const records = new Map((window.DOTS_INDEX || []).map(a => [a.id, a]));
  const params = new URLSearchParams(location.search);
  fields.forEach(k => { inputs[k].value = params.get(k) || ''; });
  function filter() {
    const state = Object.fromEntries(fields.map(k => [k, inputs[k].value.trim()]));
    const invalid = state.from && state.to && state.from > state.to;
    document.getElementById('filter-error').textContent = invalid ? '起始日期不能晚于结束日期。' : '';
    const terms = state.q.toLocaleLowerCase().split(/\s+/).filter(Boolean);
    let count = 0;
    document.querySelectorAll('.card').forEach(card => {
      const a = records.get(card.dataset.id);
      const haystack = a ? [a.title, a.summary, a.series, a.date, ...a.topics, a.text].join(' ').toLocaleLowerCase() : '';
      const visible = !invalid && a && (!state.series || a.series === state.series) && (!state.from || a.date >= state.from) && (!state.to || a.date <= state.to) && terms.every(term => haystack.includes(term));
      card.hidden = !visible;
      if (visible) count++;
    });
    document.getElementById('count').textContent = `${count} 篇文章`;
    document.getElementById('no-results').hidden = count > 0 || invalid;
    const query = new URLSearchParams();
    fields.forEach(k => { if (state[k]) query.set(k, state[k]); });
    history.replaceState(null, '', location.pathname + (query.size ? '?' + query : '') + location.hash);
  }
  form.addEventListener('submit', event => event.preventDefault());
  form.addEventListener('input', filter);
  form.addEventListener('change', filter);
  form.addEventListener('reset', () => setTimeout(filter, 0));
  filter();
}());
