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
    this.style = {};
    this.listeners = {};
    this.disabled = false;
    this._textContent = '';
  }

  appendChild(child) {
    this.children.push(child);
    return child;
  }

  remove() {
    this.removed = true;
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

  setSelectionRange() {}

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
    this._textContent = String(value ?? '');
  }

  get textContent() {
    return this._textContent;
  }

  set innerHTML(value) {
    this._textContent = String(value ?? '');
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

  contains(element) {
    return this.children.some(
      (child) => child === element || child.contains(element),
    );
  }
}

class FakeDocument {
  constructor() {
    this.body = new FakeElement('body');
    this.head = new FakeElement('head');
    this.readyState = 'complete';
    this.visibilityState = 'visible';
    this.listeners = {};
    this.currentScript = { getAttribute: () => null };
  }

  addEventListener(event, listener) {
    this.listeners[event] = listener;
  }

  dispatch(event) {
    this.listeners[event]?.({});
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

class FakeClock {
  constructor() {
    this.now = 0;
    this.nextId = 1;
    this.timeouts = new Map();
    this.intervals = new Map();
  }

  setTimeout(callback, delay = 0) {
    const id = this.nextId++;
    this.timeouts.set(id, { callback, at: this.now + delay, delay });
    return id;
  }

  clearTimeout(id) {
    this.timeouts.delete(id);
  }

  setInterval(callback, delay) {
    const id = this.nextId++;
    this.intervals.set(id, { callback, delay, at: this.now + delay });
    return id;
  }

  clearInterval(id) {
    this.intervals.delete(id);
  }

  // Delay of the earliest pending timeout, or null when nothing is queued.
  // minDelay skips UI timers such as the 300ms focus delay after opening.
  nextTimeoutDelay(minDelay = 0) {
    const pending = [...this.timeouts.values()]
      .filter((timer) => timer.delay >= minDelay)
      .sort((a, b) => a.at - b.at);
    return pending.length ? pending[0].delay : null;
  }

  runNextTimeout(minDelay = 0) {
    const pending = [...this.timeouts.entries()]
      .filter(([, timer]) => timer.delay >= minDelay)
      .sort((a, b) => a[1].at - b[1].at);
    if (!pending.length) return false;
    const [id, timer] = pending[0];
    this.timeouts.delete(id);
    this.now = Math.max(this.now, timer.at);
    timer.callback();
    return true;
  }

  tick(ms) {
    const target = this.now + ms;
    for (let guard = 0; guard < 200; guard++) {
      const due = [
        ...[...this.timeouts.entries()].map(([id, timer]) => ({
          id,
          at: timer.at,
          run: () => {
            this.timeouts.delete(id);
            this.now = timer.at;
            timer.callback();
          },
        })),
        ...[...this.intervals.entries()].map(([id, timer]) => ({
          id,
          at: timer.at,
          run: () => {
            timer.at += timer.delay;
            this.now = Math.max(this.now, timer.at - timer.delay);
            timer.callback();
          },
        })),
      ]
        .filter((candidate) => candidate.at <= target)
        .sort((a, b) => a.at - b.at);
      if (!due.length) break;
      due[0].run();
    }
    this.now = target;
  }
}

class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 3;
  static instances = [];

  constructor(url) {
    this.url = url;
    this.readyState = FakeWebSocket.CONNECTING;
    this.sent = [];
    this.onopen = null;
    this.onmessage = null;
    this.onerror = null;
    this.onclose = null;
    FakeWebSocket.instances.push(this);
  }

  send(payload) {
    if (this.readyState !== FakeWebSocket.OPEN) {
      throw new Error('socket is not open');
    }
    this.sent.push(payload);
  }

  open() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }

  receive(message) {
    this.onmessage?.({ data: JSON.stringify(message) });
  }

  drop() {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.({});
  }

  close() {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.({});
  }
}

async function flushMicrotasks() {
  // submitVerification chains two promise callbacks before connecting.
  for (let i = 0; i < 5; i++) await Promise.resolve();
}

async function launchWidget() {
  FakeWebSocket.instances = [];
  const clock = new FakeClock();
  const document = new FakeDocument();
  const window = {
    location: { href: 'https://embed.test/' },
    crypto: { randomUUID: () => '00000000-0000-4000-8000-000000000000' },
    sessionStorage: { getItem: () => null, setItem: () => {} },
    listeners: {},
    addEventListener(event, listener) {
      this.listeners[event] = listener;
    },
    dispatch(event) {
      this.listeners[event]?.({});
    },
  };
  const context = vm.createContext({
    document,
    URL,
    Math,
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
    setTimeout: (callback, delay) => clock.setTimeout(callback, delay),
    clearTimeout: (id) => clock.clearTimeout(id),
    setInterval: (callback, delay) => clock.setInterval(callback, delay),
    clearInterval: (id) => clock.clearInterval(id),
  });

  vm.runInContext(widgetSource, context, { filename: widgetPath });
  const root = document.getElementById('langbot-widget-root');
  assert.ok(root, 'widget should initialize');
  root.shadowRoot.querySelector('.lb-bubble').click();
  await flushMicrotasks();
  const socket = FakeWebSocket.instances.at(-1);
  assert.ok(socket, 'opening widget should connect its WebSocket');

  return {
    clock,
    document,
    window,
    root,
    currentSocket: () => FakeWebSocket.instances.at(-1),
    connect(socketInstance = FakeWebSocket.instances.at(-1)) {
      socketInstance.open();
      socketInstance.receive({
        type: 'connected',
        connection_id: `conn-${FakeWebSocket.instances.length}`,
      });
    },
    statusBanner: () => root.shadowRoot.querySelector('.lb-conn-status'),
    sendBtn: () => root.shadowRoot.querySelector('.lb-send-btn'),
  };
}

test('retries forever after a drop instead of giving up', async () => {
  const widget = await launchWidget();
  widget.connect();
  assert.equal(widget.sendBtn().disabled, false);

  widget.currentSocket().drop();
  assert.equal(widget.sendBtn().disabled, true);
  assert.ok(widget.statusBanner().classList.contains('lb-visible'));

  const delays = [];
  for (let attempt = 0; attempt < 10; attempt++) {
    const delay = widget.clock.nextTimeoutDelay(1000);
    assert.notEqual(delay, null, `attempt ${attempt} should schedule a retry`);
    delays.push(delay);
    assert.equal(widget.clock.runNextTimeout(1000), true);
    assert.ok(
      FakeWebSocket.instances.length === attempt + 2,
      `attempt ${attempt} should open a new socket`,
    );
    // Fail this retry without ever reaching the authenticated handshake.
    widget.currentSocket().drop();
  }

  // Exponential backoff with jitter, capped at 30s.
  assert.ok(delays[0] >= 3000 && delays[0] < 4000);
  assert.ok(delays[1] >= 6000 && delays[1] < 7000);
  assert.ok(delays.at(-1) <= 31000, 'delay must stay under the 30s cap');
  assert.ok(delays.at(-1) >= 30000, 'delay should reach the 30s cap');
});

test('recovers as soon as the connection succeeds again', async () => {
  const widget = await launchWidget();
  widget.connect();
  const first = widget.currentSocket();
  first.drop();

  while (
    FakeWebSocket.instances.length === 1 &&
    widget.clock.runNextTimeout(1000)
  ) {
    // Let the backoff reach the actual connect attempt.
  }
  assert.equal(FakeWebSocket.instances.length, 2);
  widget.connect();

  assert.ok(!widget.statusBanner().classList.contains('lb-visible'));
  assert.equal(widget.sendBtn().disabled, false);
  assert.equal(widget.statusBanner().textContent, '');
});

test('a network-online event skips the remaining backoff', async () => {
  const widget = await launchWidget();
  widget.connect();
  widget.currentSocket().drop();

  const before = FakeWebSocket.instances.length;
  widget.window.dispatch('online');

  assert.equal(FakeWebSocket.instances.length, before + 1);
  assert.equal(widget.clock.nextTimeoutDelay(1000), null);
});

test('a hidden tab waits for visibility before retrying', async () => {
  const widget = await launchWidget();
  widget.connect();
  widget.document.visibilityState = 'hidden';
  widget.currentSocket().drop();

  assert.equal(widget.clock.nextTimeoutDelay(1000), null);
  assert.equal(FakeWebSocket.instances.length, 1);

  widget.document.visibilityState = 'visible';
  widget.document.dispatch('visibilitychange');

  assert.equal(FakeWebSocket.instances.length, 2);
});

test('replaces a socket that never answers its heartbeat', async () => {
  const widget = await launchWidget();
  widget.connect();
  const original = widget.currentSocket();

  // First heartbeat: no pong. One miss resets nothing yet.
  widget.clock.tick(30000);
  assert.equal(FakeWebSocket.instances.length, 1);
  assert.ok(original.sent.includes(JSON.stringify({ type: 'ping' })));

  widget.clock.tick(10000);
  assert.equal(FakeWebSocket.instances.length, 1);

  // Second heartbeat also unanswered: the zombie socket is replaced.
  widget.clock.tick(20000);
  widget.clock.tick(10000);
  widget.clock.tick(1);
  assert.equal(FakeWebSocket.instances.length, 2);
  assert.ok(original.readyState === FakeWebSocket.CLOSED);
});
