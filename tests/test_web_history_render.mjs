import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';

const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const start = html.indexOf('    let lastKnownMsgId = 0;');
const end = html.indexOf('    async function fetchNewMessages()', start);
assert.ok(start >= 0 && end > start, 'Web history renderer must be present');

function renderer() {
    const displayed = [];
    const context = vm.createContext({
        appendMessage: (text, role) => displayed.push({ text, role }),
        AbortController,
        fetch: () => { throw new Error('Network access is forbidden in this test'); },
        setTimeout,
        clearTimeout,
    });
    vm.runInContext(html.slice(start, end), context);
    return { context, displayed, run: (source) => vm.runInContext(source, context) };
}

test('two intentional identical Web sends remain visible', () => {
    const { displayed, run } = renderer();
    run('appendUserMessageOnce("Καλημέρα"); appendUserMessageOnce("Καλημέρα");');
    assert.equal(displayed.length, 2);
});

test('distinct persisted rows with identical text render once each', () => {
    const { displayed, run } = renderer();
    run(`renderHistoryMsg({rowid: 101, role: 'user', content: 'Καλημέρα', channel: 'web'});
         renderHistoryMsg({rowid: 102, role: 'user', content: 'Καλημέρα', channel: 'web'});
         renderHistoryMsg({rowid: 101, role: 'user', content: 'Καλημέρα', channel: 'web'});`);
    assert.equal(displayed.length, 2);
});

test('HTTP and history events reconcile optimistic echoes by row ID', () => {
    const { displayed, run } = renderer();
    run(`appendUserMessageOnce('Γεια');
         acknowledgeLocalEcho('user', 'Γεια', 201);
         renderHistoryMsg({rowid: 201, role: 'user', content: 'Γεια', channel: 'web'});
         appendAssistantResponseOnce('Γεια σου', 'Chat_Agent', 202);
         renderHistoryMsg({rowid: 202, role: 'assistant', content: 'Γεια σου', channel: 'web'});`);
    assert.deepEqual(displayed.map(({ text }) => text), ['Γεια', 'Γεια σου']);
});

test('history arriving before HTTP response does not duplicate assistant reply', () => {
    const { displayed, run } = renderer();
    run(`appendUserMessageOnce('Γεια');
         renderHistoryMsg({rowid: 301, role: 'user', content: 'Γεια', channel: 'web'});
         renderHistoryMsg({rowid: 302, role: 'assistant', content: 'Γεια σου', channel: 'web'});
         acknowledgeLocalEcho('user', 'Γεια', 301);
         appendAssistantResponseOnce('Γεια σου', 'Chat_Agent', 302);`);
    assert.deepEqual(displayed.map(({ text }) => text), ['Γεια', 'Γεια σου']);
});

test('two identical Web turns survive HTTP, WebSocket and polling replay', () => {
    const { displayed, run } = renderer();
    run(`appendUserMessageOnce('Ίδιο μήνυμα');
         appendUserMessageOnce('Ίδιο μήνυμα');
         acknowledgeLocalEcho('user', 'Ίδιο μήνυμα', 401);
         appendAssistantResponseOnce('Ίδια απάντηση', 'Chat_Agent', 403);
         renderHistoryMsg({rowid: 402, role: 'user', content: 'Ίδιο μήνυμα', channel: 'web'});
         renderHistoryMsg({rowid: 404, role: 'assistant', content: 'Ίδια απάντηση', channel: 'web'});
         acknowledgeLocalEcho('user', 'Ίδιο μήνυμα', 402);
         appendAssistantResponseOnce('Ίδια απάντηση', 'Chat_Agent', 404);
         for (const rowid of [401, 402, 403, 404]) {
             renderHistoryMsg({rowid, role: rowid < 403 ? 'user' : 'assistant',
                 content: rowid < 403 ? 'Ίδιο μήνυμα' : 'Ίδια απάντηση', channel: 'web'});
         }`);
    assert.deepEqual(displayed.map(({ text }) => text),
        ['Ίδιο μήνυμα', 'Ίδιο μήνυμα', 'Ίδια απάντηση', 'Ίδια απάντηση']);
});
