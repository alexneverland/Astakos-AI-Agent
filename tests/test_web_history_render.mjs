import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';

const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const start = html.indexOf('    let lastKnownMsgId = 0;');
const end = html.indexOf('    async function fetchNewMessages()', start);
const sendStart = html.indexOf('    async function sendMessage()');
const sendEnd = html.indexOf("    sendBtn.addEventListener('click', sendMessage);", sendStart);
assert.ok(start >= 0 && end > start, 'Web history renderer must be present');
assert.ok(sendStart >= 0 && sendEnd > sendStart, 'Web send handler must be present');

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

function uploadRenderer() {
    const displayed = [];
    let completeUpload;
    const uploadResponse = new Promise((resolve) => { completeUpload = resolve; });
    const chatBox = {
        appendChild: (element) => { element.parentNode = chatBox; },
        removeChild: (element) => { element.parentNode = null; },
        scrollHeight: 0,
        scrollTop: 0,
    };
    const context = vm.createContext({
        appendMessage: (text, role) => displayed.push({ text, role }),
        AbortController,
        FormData,
        fetch: () => uploadResponse,
        document: { createElement: () => ({ parentNode: null }) },
        userInput: { value: '', focus() {} },
        fileInput: { files: [{ name: 'photo.png' }] },
        pastedVirtualFile: null,
        clearPendingAttachmentUI() {},
        setCoreState() {},
        isRecording: false,
        isLiveVoiceMode: false,
        currentPhotoPath: null,
        chatBox,
        setTimeout,
        clearTimeout,
    });
    vm.runInContext(html.slice(start, end) + '\n' + html.slice(sendStart, sendEnd), context);
    return {
        displayed,
        run: (source) => vm.runInContext(source, context),
        completeUpload: () => completeUpload({ok: true, json: async () => ({
            status: 'success',
            user_rowid: 501,
            assistant_rowid: 502,
            user_message: '📎 Ανέβασα αρχείο: photo.png',
            ai_message: 'Ωραία φωτογραφία!',
        })}),
        failUpload: () => completeUpload({ok: false, json: async () => ({status: 'error', message: 'Upload failed'})}),
    };
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

for (const historyFirst of [false, true]) {
    test(`Web upload shows one user and one assistant when ${historyFirst ? 'history' : 'HTTP'} arrives first`, async () => {
        const { displayed, run, completeUpload } = uploadRenderer();
        const upload = run('sendMessage()');
        const history = () => run(`renderHistoryMsg({rowid: 501, role: 'user', content: '📎 Ανέβασα αρχείο: photo.png', channel: 'web'});
            renderHistoryMsg({rowid: 502, role: 'assistant', content: 'Ωραία φωτογραφία!', channel: 'web'});`);
        if (historyFirst) history();
        completeUpload();
        await upload;
        if (!historyFirst) history();
        assert.deepEqual(displayed.map(({ role }) => role), ['user', 'ai']);
    });
}

test('failed Web upload does not leave a phantom user or assistant message', async () => {
    const { displayed, run, failUpload } = uploadRenderer();
    const upload = run('sendMessage()');
    failUpload();
    await upload;
    assert.deepEqual(displayed.map(({ role }) => role), ['ai']);
});
