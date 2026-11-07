import test from 'node:test';
import assert from 'node:assert/strict';
import { prepare } from './src/model.mjs';
import { stackModel, hourlySlots, dayBoundary, comparisonProvenance } from './src/calendar-stack.mjs';
const record = (id, start, end) => prepare([{ source: 'test', session_id: id, code: id, title: id, start_local: start, end_local: end }], [])[0];
const day = '2026-11-30';

test('import is DOM-free and every hour starts once with separate continuing members', () => {
  const a = record('a', `${day}T08:15:00-08:00`, `${day}T10:00:00-08:00`);
  const b = record('b', `${day}T08:40:00-08:00`, `${day}T09:00:00-08:00`);
  const slots = hourlySlots([b, a, a], day, 480, 600);
  assert.deepEqual(slots[0].starts.map(r => r.session.code), ['a', 'b']);
  assert.deepEqual(slots[1].ongoing.map(r => r.session.code), ['a']);
  assert.equal(slots[2].ongoing.length, 0);
  assert.equal(slots.flatMap(slot => slot.starts).length, 2);
});

test('cross-midnight intervals clip by instant and keep next-day continuations reachable', () => {
  const a = record('night', `${day}T23:30:00-08:00`, '2026-12-01T01:30:00-08:00');
  const model = stackModel([a, a], [day, '2026-12-01']);
  assert.equal(model.firstHour, 0); assert.equal(model.lastHour, 1380);
  assert.equal(model.days[0].total, 1); assert.equal(model.days[1].total, 1);
  assert.equal(model.days[1].starts, 0); assert.equal(model.days[1].continuingFromEarlierDay, 1);
  assert.equal(model.days[0].slots.find(s => s.hour === 1380).starts.length, 1);
  assert.equal(model.days[1].slots.find(s => s.hour === 0).ongoing.length, 1);
  assert.equal(model.days[1].slots.find(s => s.hour === 60).ongoing.length, 1);
  assert.equal(model.days[1].slots.find(s => s.hour === 120).ongoing.length, 0);
});

test('boundary end is excluded and source timestamp offsets are respected', () => {
  const a = record('offset', '2026-12-01T07:30:00Z', '2026-12-01T08:00:00Z');
  const model = stackModel([a], [day, '2026-12-01']);
  assert.equal(model.days[0].total, 1); assert.equal(model.days[1].total, 0);
  assert.equal(dayBoundary(day), Date.parse(`${day}T00:00:00-08:00`));
  assert.equal(dayBoundary('2026-07-01'), Date.parse('2026-07-01T00:00:00-07:00'));
});

test('early and late intervals remain in range, unknown times remain outside hourly totals', () => {
  const early = record('early', `${day}T06:15:00-08:00`, `${day}T07:10:00-08:00`);
  const late = record('late', `${day}T21:30:00-08:00`, `${day}T23:15:00-08:00`);
  const unknown = record('unknown', '', '');
  const model = stackModel([late, unknown, early, unknown], [day]);
  assert.equal(model.firstHour, 360); assert.equal(model.lastHour, 1380);
  assert.equal(model.days[0].total, 2); assert.equal(model.untimed.length, 1);
  assert.equal(model.days[0].slots.find(s => s.hour === 1380).ongoing[0], late);
});

test('empty view has 08:00 through 18:00 and same-hour records sort deterministically', () => {
  const model = stackModel([], [day]); assert.equal(model.hours[0], 480); assert.equal(model.hours.at(-1), 1080);
  const z = record('Z', `${day}T09:00:00-08:00`, `${day}T09:30:00-08:00`);
  const a = record('A', `${day}T09:00:00-08:00`, `${day}T09:30:00-08:00`);
  assert.deepEqual(hourlySlots([z, a], day, 540, 540)[0].starts.map(r => r.session.code), ['A', 'Z']);
});


test('comparison shows taxonomy labels and readable evidence without mixing source groups', () => {
  const input = record('AI', `${day}T09:00:00-08:00`, `${day}T10:00:00-08:00`);
  Object.assign(input.session, {
    tags: ['Official service'],
    system_topics: ['genai', { id: 'agents', label: 'Embedded agents label' }, 'unknown-topic'],
    classification_reasons: [{ id: 'genai', reason: 'Title names a model', evidence: [{ field: 'title', match: 'OpenAI', excerpt: 'Build with OpenAI' }] }],
    derived_company_matches: [{ company: 'OpenAI', field: 'abstract', excerpt: 'Uses OpenAI models' }],
  });
  const result = comparisonProvenance(input, [{ id: 'genai', label: '生成式 AI' }, { id: 'agents', label: '代理程式' }]);
  assert.deepEqual(result.system, ['生成式 AI', '代理程式', 'unknown-topic']);
  assert.deepEqual(result.official, ['Official service']);
  assert.deepEqual(result.companies, ['OpenAI']);
  assert.deepEqual(result.evidence, [
    '生成式 AI：Title names a model',
    '生成式 AI · 標題：「Build with OpenAI」',
    'OpenAI · 摘要：「Uses OpenAI models」',
  ]);
  assert.equal(comparisonProvenance({ session: {} }).evidence.length, 0);
});
