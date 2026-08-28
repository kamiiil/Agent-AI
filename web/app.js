const messagesEl = document.querySelector('#messages');
const form = document.querySelector('#chat-form');
const promptEl = document.querySelector('#prompt');
const introEl = document.querySelector('.intro');
const nutritionEl = document.querySelector('#nutrition-content');
const measurementsEl = document.querySelector('#measurements-content');
const scrollToLatestEl = document.querySelector('#scroll-to-latest');
let conversation = [];

function isMessagesAtBottom() {
  return messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 24;
}

function updateScrollToLatest() {
  scrollToLatestEl.classList.toggle('visible', !isMessagesAtBottom());
}

function addMessage(text, role) {
  const element = document.createElement('div');
  element.className = `message ${role}`;
  element.textContent = text;
  messagesEl.append(element);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  updateScrollToLatest();
}

function renderNutrition(event) {
  const result = event.result || {};
  if (!result.found) {
    nutritionEl.innerHTML = `<div class="empty-state"><span class="empty-icon">⌁</span><p>${result.message || 'Nie znaleziono produktu.'}</p></div>`;
    return;
  }
  const nutrition = result.nutrition_per_100g || {};
  const formatNutritionValue = value => Number(value).toFixed(1);
  const nutrients = [['protein_g_100g', 'Białko', 'g'], ['carbohydrates_g_100g', 'Węglowodany', 'g'], ['fat_g_100g', 'Tłuszcz', 'g'], ['sugars_g_100g', 'Cukry', 'g'], ['fiber_g_100g', 'Błonnik', 'g'], ['salt_g_100g', 'Sól', 'g']];
  const cards = nutrients.filter(([key]) => nutrition[key] != null).map(([key, label, unit]) => `<div class="nutrient"><b>${formatNutritionValue(nutrition[key])}${unit}</b><span>${label}</span></div>`).join('');
  const calories = nutrition.energy_kcal_100g == null ? '—' : formatNutritionValue(nutrition.energy_kcal_100g);
  nutritionEl.innerHTML = `<div class="nutrition-card"><strong>${result.product_name || 'Produkt'}</strong><div class="product-meta">${result.brand || 'OpenFoodFacts'}${result.serving_size ? ` · porcja ${result.serving_size}` : ''}</div><div class="kcal">${calories} <small>kcal / 100 g</small></div><div class="nutrient-grid">${cards || '<span class="product-meta">Brak szczegółowych makroskładników.</span>'}</div></div>`;
}

function renderMeasurements(data) {
  if (!data.found) {
    measurementsEl.innerHTML = '<div class="empty-measurements">Nie ma jeszcze zapisanych pomiarów. Podaj masę lub obwód w rozmowie, a FitMentor zapisze dane lokalnie.</div>';
    return;
  }
  const latest = data.latest || {};
  const history = data.history || [];
  const circumferences = Object.entries(latest.circumferences_cm || {});
  const latestDate = history[0]?.recorded_at ? new Date(history[0].recorded_at) : null;
  const formatDate = value => new Date(value).toLocaleDateString('pl-PL', { day: 'numeric', month: 'short', year: 'numeric' });
  const labelForMuscle = name => ({ biceps: 'Biceps', udo: 'Udo', klatka: 'Klatka piersiowa', pas: 'Pas', lydka: 'Łydka', barki: 'Barki' }[name] || name);
  const circumferenceCards = circumferences.map(([name, value]) => `<div class="stat-card"><span class="stat-label">${labelForMuscle(name)}</span><strong>${value}</strong><small>cm</small></div>`).join('');
  const historyRows = history.slice(0, 6).map(row => {
    const details = [];
    if (row.weight_kg != null) details.push(`${row.weight_kg} kg`);
    details.push(...Object.entries(row.circumferences_cm || {}).map(([name, value]) => `${labelForMuscle(name)} ${value} cm`));
    return `<div class="history-row"><span>${formatDate(row.recorded_at)}</span><strong>${details.join(' · ') || 'Brak szczegółów'}</strong></div>`;
  }).join('');
  measurementsEl.innerHTML = `<div class="stats-summary"><div><span class="stat-label">Aktualna masa</span><strong>${latest.weight_kg ?? '—'}<small> kg</small></strong></div><div><span class="stat-label">Liczba pomiarów</span><strong>${history.length}</strong></div><div><span class="stat-label">Ostatni pomiar</span><strong>${latestDate ? formatDate(latestDate) : '—'}</strong></div></div><div class="stats-section"><div class="stats-section-heading"><span class="eyebrow">Aktualny stan</span><span class="stats-count">${circumferences.length} obw.</span></div><div class="stats-grid">${circumferenceCards || '<div class="stats-no-data">Brak zapisanych obwodów</div>'}</div></div><div class="history"><span class="eyebrow">Historia pomiarów</span>${historyRows}</div>`;
}

async function refreshMeasurements() {
  try { renderMeasurements(await (await fetch('/api/measurements')).json()); }
  catch { measurementsEl.innerHTML = '<div class="empty-measurements">Nie udało się odczytać pomiarów.</div>'; }
}

async function sendPrompt(prompt) {
  introEl.classList.add('hidden');
  addMessage(prompt, 'user');
  promptEl.value = '';
  const button = form.querySelector('button');
  button.disabled = true;
  button.querySelector('span').textContent = 'Chwila';
  try {
    const response = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prompt, messages: conversation }) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error);
    conversation = data.messages;
    addMessage(data.answer, 'assistant');
    const nutritionEvent = (data.tool_events || []).find(event => event.name === 'analyze_product');
    if (nutritionEvent) renderNutrition(nutritionEvent);
    if ((data.tool_events || []).some(event => ['save_body_measurements', 'get_body_measurements'].includes(event.name))) refreshMeasurements();
  } catch (error) { addMessage(`Nie udało się połączyć z FitMentorem: ${error.message}`, 'assistant'); }
  button.disabled = false;
  button.querySelector('span').textContent = 'Wyślij';
}

form.addEventListener('submit', event => { event.preventDefault(); const prompt = promptEl.value.trim(); if (prompt) sendPrompt(prompt); });
promptEl.addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); form.requestSubmit(); } });
document.querySelectorAll('[data-prompt]').forEach(button => button.addEventListener('click', () => sendPrompt(button.dataset.prompt)));
document.querySelector('#refresh-measurements').addEventListener('click', refreshMeasurements);
messagesEl.addEventListener('scroll', updateScrollToLatest);
scrollToLatestEl.addEventListener('click', () => messagesEl.scrollTo({ top: messagesEl.scrollHeight, behavior: 'smooth' }));
addMessage('Jestem FitMentor. Mogę pomóc Ci z treningiem, jedzeniem i śledzeniem postępów.', 'assistant');
refreshMeasurements();
