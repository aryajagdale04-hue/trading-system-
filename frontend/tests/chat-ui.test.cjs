const test = require('node:test');
const assert = require('node:assert/strict');
global.window = {};
require('../chat-ui.js');

test('citations allow only credential-free HTTP and HTTPS links', () => {
  assert.equal(window.StockChat.safeCitationUrl('https://example.com/story'), 'https://example.com/story');
  assert.equal(window.StockChat.safeCitationUrl('http://example.com'), 'http://example.com/');
  for (const bad of ['javascript:alert(1)', 'data:text/html,x', 'file:///etc/passwd', '/relative', 'https://user:pw@example.com']) {
    assert.equal(window.StockChat.safeCitationUrl(bad), null);
  }
});

test('chat answer rendering accepts text but never stringifies provider objects', () => {
  assert.equal(window.StockChat.answerText({ answer: 'Reliance is an Indian company.' }), 'Reliance is an Indian company.');
  assert.equal(window.StockChat.answerText({ answer: { text: 'Plain text answer.' } }), 'Plain text answer.');
  assert.equal(window.StockChat.answerText({ answer: { unexpected: 'shape' } }), null);
  assert.equal(window.StockChat.answerText({ answer: { toString: () => 'bad' } }), null);
});

test('chat company lookup text normalization is stable', () => {
  assert.equal(window.StockChat.normalizeLookupText('Reliance Industries, Ltd.'), 'reliance industries ltd');
  assert.equal(window.StockChat.readableAnswer('## What is it?\n\n* **Jio:** a mobile network.\n\n---'), 'What is it?\n\n• Jio: a mobile network.');
});

test('chat renders untrusted model content as text and creates anchors only from sources', () => {
  const fs = require('node:fs');
  const code = fs.readFileSync(require.resolve('../chat-ui.js'), 'utf8');
  assert.match(code, /bubble\s*=\s*element\("article"[^;]*item\.content/);
  assert.match(code, /node\.textContent\s*=\s*text/);
  assert.match(code, /source\.url/);
  assert.doesNotMatch(code, /innerHTML\s*=/);
});
