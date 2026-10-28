import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const testDirectory = path.dirname(fileURLToPath(import.meta.url));
const widgetPath = path.resolve(
  testDirectory,
  '../../../src/langbot/templates/embed/widget.js',
);
const widgetSource = fs.readFileSync(widgetPath, 'utf8');

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.className = '';
    this.dataset = {};
    this.style = {};
    this.listeners = {};
    this._innerHTML = '';
  }

  appendChild(child) {
    this.children.push(child);
    return child;
  }

  setAttribute(name, value) {
    this[name] = String(value);
  }

  addEventListener(event, listener) {
    this.listeners[event] = listener;
  }

  click() {
    this.listeners.click?.({});
  }

  focus() {
    this.focused = true;
  }

  setSelectionRange(start, end) {
    this.selectionStart = start;
    this.selectionEnd = end;
  }

  get scrollHeight() {
    return 40;
  }

  attachShadow() {
    this.shadowRoot = new FakeElement('shadow-root');
    return this.shadowRoot;
  }

  get classList() {
    return {
      add: (...names) => {
        const classes = `${this.className} ${names.join(' ')}`
          .trim()
          .split(/\s+/);
        this.className = [...new Set(classes)].join(' ');
      },
    };
  }

  set textContent(value) {
    this._innerHTML = String(value ?? '');
  }

  set innerHTML(value) {
    this._innerHTML = String(value ?? '');
  }

  get innerHTML() {
    return this._innerHTML;
  }

  querySelectorAll(selector) {
    const matches = [];
    for (const child of this.children) {
      if (
        selector.startsWith('.') &&
        child.className.split(/\s+/).includes(selector.slice(1))
      ) {
        matches.push(child);
      }
      matches.push(...child.querySelectorAll(selector));
    }
    return matches;
  }

  querySelector(selector) {
    return this.querySelectorAll(selector)[0] ?? null;
  }
}

class FakeDocument {
  constructor() {
    this.body = new FakeElement('body');
    this.head = new FakeElement('head');
    this.readyState = 'complete';
    this.currentScript = { getAttribute: () => null };
  }

  createElement(tagName) {
    return new FakeElement(tagName);
  }

  getElementById(id) {
    const find = (element) => {
      if (element.id === id) return element;
      for (const child of element.children) {
        const match = find(child);
        if (match) return match;
      }
      return null;
    };
    return find(this.body) ?? find(this.head);
  }
}

class FakeWebSocket {
  static OPEN = 1;
  static instances = [];

  constructor(url) {
    this.url = url;
    this.readyState = FakeWebSocket.OPEN;
    this.sent = [];
    FakeWebSocket.instances.push(this);
  }

  send(payload) {
    this.sent.push(payload);
  }
}

function launchWidget(options = {}) {
  FakeWebSocket.instances = [];
  const document = new FakeDocument();
  const window = {
    location: { href: 'https://embed.test/' },
    crypto: { randomUUID: () => '00000000-0000-4000-8000-000000000000' },
    sessionStorage: { getItem: () => null, setItem: () => {} },
  };
  const context = vm.createContext({
    document,
    URL,
    window,
    navigator: { clipboard: { writeText: () => Promise.resolve() } },
    WebSocket: FakeWebSocket,
    fetch: () => new Promise(() => {}),
    requestAnimationFrame: () => 0,
    setTimeout: () => 0,
    clearTimeout: () => {},
    setInterval: () => 0,
    clearInterval: () => {},
  });

  const source =
    options.quickQuestions === undefined
      ? widgetSource
      : widgetSource.replace(
          '"__LANGBOT_QUICK_QUESTIONS__"',
          JSON.stringify(options.quickQuestions),
        );

  vm.runInContext(source, context, { filename: widgetPath });
  const root = document.getElementById('langbot-widget-root');
  assert.ok(root, 'widget should initialize');
  root.shadowRoot.querySelector('.lb-bubble').click();
  const socket = FakeWebSocket.instances.at(-1);
  assert.ok(socket, 'opening widget should connect its WebSocket');

  return {
    root,
    socket,
    receive(message) {
      socket.onmessage({
        data: JSON.stringify({ type: 'response', data: message }),
      });
    },
    assistantMessages() {
      return root.shadowRoot.querySelectorAll('.lb-msg-assistant');
    },
  };
}

function assistant(id, content) {
  return { id, role: 'assistant', content, is_final: true };
}

test('renders a non-empty reply after an empty assistant frame', () => {
  const widget = launchWidget();

  widget.receive(assistant('thought', ''));
  widget.receive(assistant('answer', 'visible answer'));

  const messages = widget.assistantMessages();
  assert.equal(messages.length, 2);
  assert.equal(
    messages[1].querySelector('.lb-msg-bubble').innerHTML,
    'visible answer',
  );
});

test('still drops a duplicate non-empty assistant frame', () => {
  const widget = launchWidget();

  widget.receive(assistant('answer-1', 'same answer'));
  widget.receive(assistant('answer-2', 'same answer'));

  assert.equal(widget.assistantMessages().length, 1);
});

test('still keeps two distinct non-empty assistant frames', () => {
  const widget = launchWidget();

  widget.receive(assistant('answer-1', 'first answer'));
  widget.receive(assistant('answer-2', 'second answer'));

  assert.equal(widget.assistantMessages().length, 2);
});

test('renders configured quick questions under the welcome message', () => {
  const widget = launchWidget({
    quickQuestions: ['How do I start?', 'Pricing?'],
  });

  const welcome = widget.root.shadowRoot.querySelector('.lb-welcome');
  assert.equal(welcome.querySelectorAll('.lb-quick-btn').length, 2);

  const dock = widget.root.shadowRoot.querySelector('.lb-quick-dock');
  assert.ok(dock, 'a dock is created when questions are configured');
  assert.equal(dock.style.display, 'none');
});

test('clicking a quick question fills the input without sending', () => {
  const widget = launchWidget({ quickQuestions: ['How do I start?'] });

  const input = widget.root.shadowRoot.querySelector('.lb-input');
  const button = widget.root.shadowRoot.querySelector('.lb-quick-btn');
  button.click();

  assert.equal(input.value, 'How do I start?');
  assert.equal(input.focused, true);
  assert.equal(input.selectionStart, 'How do I start?'.length);
  assert.equal(input.selectionEnd, 'How do I start?'.length);
  assert.equal(
    widget.socket.sent.filter((payload) =>
      String(payload).includes('"type":"message"'),
    ).length,
    0,
  );
});

test('shows the dock and hides the welcome after the conversation starts', () => {
  const widget = launchWidget({ quickQuestions: ['Q1', 'Q2'] });

  widget.receive(assistant('a1', 'hello'));

  const welcome = widget.root.shadowRoot.querySelector('.lb-welcome');
  const dock = widget.root.shadowRoot.querySelector('.lb-quick-dock');
  assert.equal(welcome.style.display, 'none');
  assert.equal(dock.style.display, 'flex');
  assert.equal(dock.querySelectorAll('.lb-quick-btn').length, 2);
});

test('does not render quick questions when none are configured', () => {
  const widget = launchWidget();

  assert.equal(
    widget.root.shadowRoot.querySelectorAll('.lb-quick-btn').length,
    0,
  );
  assert.equal(widget.root.shadowRoot.querySelector('.lb-quick-dock'), null);
});
