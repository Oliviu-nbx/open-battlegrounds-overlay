// Isolated logic tests; no browser, dependencies, tracker imports or real data.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');
const source = fs.readFileSync(path.join(__dirname, 'app.js'), 'utf8');

function fixture(saved = null, storageBlocked = false) {
  const nodes = new Map();
  const node = selector => {
    if (!nodes.has(selector)) nodes.set(selector, {
      textContent: '', innerHTML: '', dataset: {},
      addEventListener() {}, append() {}, click() {}, remove() {},
      setAttribute(name, value) { this[name] = value; },
    });
    return nodes.get(selector);
  };
  let exported;
  const context = vm.createContext({
    document: {querySelector: node, addEventListener() {}, body: node('body'), createElement: () => node('download')},
    localStorage: {
      getItem() { if (storageBlocked) throw new Error('Storage denied'); return saved; },
      setItem(_key, value) { saved = value; },
    },
    matchMedia: () => ({matches: false, addEventListener() {}}),
    Blob, URL: {createObjectURL(blob) { exported = blob; return 'blob:sample'; }, revokeObjectURL() {}},
    setTimeout(callback) {callback();},
  });
  // Bootstrap DOM construction is verified interactively, not mocked here.
  vm.runInContext(source.slice(0, source.indexOf('const mobilePhase=')), context);
  return {run: expression => vm.runInContext(expression, context), nodes, exported: () => exported};
}

test('preview fixtures separate base stats from entity stats', () => {
  const app = fixture();
  assert.equal(app.run('referenceCards[0].attack'), 3);
  assert.equal(app.run('ownBoard[0].attack'), 29);
  assert.equal(app.run('opponents.find(o => o.id === "nzoth").board.length'), 0);
});

test('aggregates include manual results and exclude incomplete matches', () => {
  const app = fixture();
  app.run('renderHistory()');
  const html = app.nodes.get('#view-history').innerHTML;
  assert.match(html, /4\.2/);
  assert.match(html, /60%/);
  assert.equal(app.run('matches.filter(m => m.placement !== null).length'), 5);
});

test('saved preferences are validated and bounded', () => {
  const app = fixture(JSON.stringify({theme: 'bad', opacity: 9, compact: 'yes', model: true}));
  assert.equal(app.run('preferences.theme'), 'dark');
  assert.equal(app.run('preferences.opacity'), 85);
  assert.equal(app.run('preferences.compact'), false);
  assert.equal(app.run('preferences.model'), true);
});

test('invalid or denied browser storage falls back safely', () => {
  for (const app of [fixture('{broken'), fixture(null, true)]) {
    assert.equal(app.run('preferences.opacity'), 96);
    assert.equal(app.run('preferences.theme'), 'dark');
  }
});

test('export contains only labeled synthetic matches', async () => {
  const app = fixture();
  app.run('exportSample()');
  const output = JSON.parse(await app.exported().text());
  assert.equal(output.synthetic, true);
  assert.equal(output.matches.length, 6);
  assert.equal(output.matches[5].placement, null);
  assert.equal(app.nodes.get('download').download, 'battlegrounds-preview-history.json');
});
