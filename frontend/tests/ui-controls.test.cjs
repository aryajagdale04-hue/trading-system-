const test = require('node:test');
const assert = require('node:assert/strict');
const controls = require('../ui-controls.js');

function fakeElement() {
  const handlers = {};
  const classes = new Set();
  return {
    dataset: {}, textContent: '', attributes: {}, scrolled: false, focused: false,
    classList: { add: (name) => classes.add(name), remove: (name) => classes.delete(name), contains: (name) => classes.has(name) },
    get classes() { return classes; },
    addEventListener(type, handler) { handlers[type] = handler; },
    setAttribute(name, value) { this.attributes[name] = value; },
    click() { handlers.click?.({ preventDefault() {} }); },
    scrollIntoView() { this.scrolled = true; },
    focus() { this.focused = true; },
  };
}

test('theme toggle starts dark, switches to light, and saves the choice', () => {
  const root = fakeElement();
  const button = fakeElement();
  const values = new Map();
  const storage = { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };
  const document = { documentElement: root, getElementById: (id) => id === 'theme-toggle' ? button : null };

  controls.initTheme(document, storage);
  assert.equal(root.dataset.theme, 'dark');
  button.click();
  assert.equal(root.dataset.theme, 'light');
  assert.equal(values.get('market-explorer-theme'), 'light');
  assert.match(button.attributes['aria-label'], /dark/i);
});

test('floating assistant opens the stock chat popup and close button hides it', () => {
  const button = fakeElement();
  const close = fakeElement();
  const section = fakeElement();
  const input = fakeElement();
  const document = { getElementById: (id) => ({ 'assistant-shortcut': button, 'assistant-chat-close': close, 'stock-chat-section': section, 'stock-chat-mount': { querySelector: () => input } })[id] || null };

  controls.initAssistantShortcut(document);
  button.click();
  assert.equal(section.classes.has('is-open'), true);
  assert.equal(button.attributes['aria-expanded'], 'true');
  assert.equal(input.focused, true);
  close.click();
  assert.equal(section.classes.has('is-open'), false);
  assert.equal(button.attributes['aria-expanded'], 'false');
});
