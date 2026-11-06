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
      remove: (...names) => {
        const removed = new Set(names);
        this.className = this.className
          .split(/\s+/)
          .filter((name) => name && !removed.has(name))
          .join(' ');
      },
      contains: (name) => this.className.split(/\s+/).includes(name),
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
  constructor(scriptAttributes = {}) {
    this.body = new FakeElement('body');
    this.head = new FakeElement('head');
    this.readyState = 'complete';
    this.visibilityState = 'visible';
    this.listeners = {};
    this.currentScript = {
      getAttribute: (name) => scriptAttributes[name] ?? null,
    };
  }

  addEventListener(event, listener) {
    this.listeners[event] = listener;
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

async function flushMicrotasks() {
  // submitVerification chains two promise callbacks before connecting.
  for (let i = 0; i < 5; i++) await Promise.resolve();
}

async function launchWidget(options = {}) {
  FakeWebSocket.instances = [];
  const document = new FakeDocument(options.scriptAttributes);
  const window = {
    location: { href: 'https://embed.test/' },
    crypto: { randomUUID: () => '00000000-0000-4000-8000-000000000000' },
    sessionStorage: { getItem: () => null, setItem: () => {} },
    listeners: {},
    addEventListener(event, listener) {
      this.listeners[event] = listener;
    },
  };
  const context = vm.createContext({
    document,
    URL,
    window,
    navigator: { clipboard: { writeText: () => Promise.resolve() } },
    WebSocket: FakeWebSocket,
    fetch: (url) => {
      // Opening the panel asks the backend to sign a session token before the
      // socket may connect; other requests stay pending like before.
      if (String(url).includes('/turnstile/verify')) {
        return Promise.resolve({
          json: () =>
            Promise.resolve({ data: { token: 'test-session-token' } }),
        });
      }
      return new Promise(() => {});
    },
    requestAnimationFrame: () => 0,
    setTimeout: () => 0,
    clearTimeout: () => {},
    setInterval: () => 0,
    clearInterval: () => {},
  });

  let source = widgetSource;
  if (options.roleGroups !== undefined) {
    source = source.replace(
      '"__LANGBOT_ROLE_GROUPS__"',
      JSON.stringify(options.roleGroups),
    );
  }
  source = source.replace(
    '"__LANGBOT_WELCOME_MESSAGE__"',
    JSON.stringify(options.welcomeMessage ?? ''),
  );

  vm.runInContext(source, context, { filename: widgetPath });
  const root = document.getElementById('langbot-widget-root');
  assert.ok(root, 'widget should initialize');
  root.shadowRoot.querySelector('.lb-bubble').click();
  await flushMicrotasks();
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

test('renders a non-empty reply after an empty assistant frame', async () => {
  const widget = await launchWidget();

  widget.receive(assistant('thought', ''));
  widget.receive(assistant('answer', 'visible answer'));

  const messages = widget.assistantMessages();
  assert.equal(messages.length, 2);
  assert.equal(
    messages[1].querySelector('.lb-msg-bubble').innerHTML,
    'visible answer',
  );
});

test('still drops a duplicate non-empty assistant frame', async () => {
  const widget = await launchWidget();

  widget.receive(assistant('answer-1', 'same answer'));
  widget.receive(assistant('answer-2', 'same answer'));

  assert.equal(widget.assistantMessages().length, 1);
});

test('still keeps two distinct non-empty assistant frames', async () => {
  const widget = await launchWidget();

  widget.receive(assistant('answer-1', 'first answer'));
  widget.receive(assistant('answer-2', 'second answer'));

  assert.equal(widget.assistantMessages().length, 2);
});

test('renders configured group questions under the welcome message', async () => {
  const widget = await launchWidget({
    roleGroups: [
      {
        id: 'g1',
        label: 'Visitors',
        questions: ['How do I start?', 'Pricing?'],
      },
    ],
  });

  const welcome = widget.root.shadowRoot.querySelector('.lb-welcome');
  assert.equal(welcome.querySelectorAll('.lb-role-question').length, 2);
  assert.equal(welcome.querySelectorAll('.lb-quick-btn').length, 0);

  const dock = widget.root.shadowRoot.querySelector('.lb-role-dock');
  assert.ok(dock, 'a role dock is created when groups are configured');
  assert.equal(dock.hidden, true);
});

test('clicking a group question fills the input without sending', async () => {
  const widget = await launchWidget({
    roleGroups: [
      { id: 'g1', label: 'Visitors', questions: ['How do I start?'] },
    ],
  });

  const input = widget.root.shadowRoot.querySelector('.lb-input');
  const button = widget.root.shadowRoot.querySelector('.lb-role-question');
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

test('shows the role dock and hides the welcome after the conversation starts', async () => {
  const widget = await launchWidget({
    roleGroups: [{ id: 'g1', label: 'Visitors', questions: ['Q1', 'Q2'] }],
  });

  widget.receive(assistant('a1', 'hello'));

  const welcome = widget.root.shadowRoot.querySelector('.lb-welcome');
  const dock = widget.root.shadowRoot.querySelector('.lb-role-dock');
  assert.equal(welcome.style.display, 'none');
  assert.equal(dock.hidden, false);
  assert.equal(dock.querySelectorAll('.lb-role-dock-preview-btn').length, 2);
});

test('does not render quick questions when none are configured', async () => {
  const widget = await launchWidget();

  assert.equal(
    widget.root.shadowRoot.querySelectorAll('.lb-role-question').length,
    0,
  );
  assert.equal(
    widget.root.shadowRoot.querySelectorAll('.lb-quick-btn').length,
    0,
  );
  assert.equal(widget.root.shadowRoot.querySelector('.lb-role-dock'), null);
  assert.equal(widget.root.shadowRoot.querySelector('.lb-quick-dock'), null);
});

test('an empty group does not fall back to another question source', async () => {
  const widget = await launchWidget({
    roleGroups: [{ id: 'g1', label: 'Empty', questions: [] }],
  });

  assert.equal(
    widget.root.shadowRoot.querySelectorAll('.lb-role-question').length,
    0,
  );
  assert.equal(
    widget.root.shadowRoot.querySelectorAll('.lb-quick-btn').length,
    0,
  );
});

function welcomeText(widget) {
  const welcome = widget.root.shadowRoot.querySelector('.lb-welcome');
  // The welcome block is logo + text (role tabs, if any, follow).
  return welcome.children[1].innerHTML;
}

test('renders the saved welcome message from the bot config', async () => {
  const widget = await launchWidget({ welcomeMessage: 'Bot hello' });

  assert.equal(welcomeText(widget), 'Bot hello');
});

test('falls back to the page subtitle when the bot has no welcome message', async () => {
  const widget = await launchWidget({
    scriptAttributes: { 'data-subtitle': 'Page hello' },
  });

  assert.equal(welcomeText(widget), 'Page hello');
});

test('an unsaved welcome draft overrides the saved message', async () => {
  const widget = await launchWidget({
    welcomeMessage: 'Bot hello',
    scriptAttributes: {
      'data-preview-welcome': 'true',
      'data-welcome': 'Draft hello',
    },
  });

  assert.equal(welcomeText(widget), 'Draft hello');
});

test('an empty welcome draft clears the saved message', async () => {
  const widget = await launchWidget({
    welcomeMessage: 'Bot hello',
    scriptAttributes: { 'data-preview-welcome': 'true' },
  });

  assert.equal(welcomeText(widget), '');
});

test('a draft preview overrides saved groups even when it is empty', async () => {
  const widget = await launchWidget({
    roleGroups: [{ id: 'saved', label: 'Saved', questions: ['Saved Q'] }],
    scriptAttributes: {
      'data-preview-roles': 'true',
      'data-roles': JSON.stringify([
        { id: 'draft', label: 'Draft', questions: ['Draft Q'] },
      ]),
    },
  });
  assert.equal(
    widget.root.shadowRoot.querySelector('.lb-q-text').innerHTML,
    'Draft Q',
  );

  const empty = await launchWidget({
    roleGroups: [{ id: 'saved', label: 'Saved', questions: ['Saved Q'] }],
    scriptAttributes: { 'data-preview-roles': 'true' },
  });
  assert.equal(
    empty.root.shadowRoot.querySelectorAll('.lb-role-question').length,
    0,
  );
  assert.equal(empty.root.shadowRoot.querySelector('.lb-role-dock'), null);
});
