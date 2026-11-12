// Exercises the built plugin through the loader API contract, without a Steam session.
import assert from 'node:assert/strict';

const state = [];
let cursor = 0;
let mounted = false;
let cleanup;
let refresh;
let timerCleared = false;
let fail = false;
const listeners = new Map();
const notifications = [];
let snapshot = {
    version: 1, updated_at: Date.now() / 1000, status: 'compiling',
    active: {name: 'Example Game', percent: 62, stage: 2, done: 100, total: 200,
        elapsed_seconds: 30, eta_seconds: 10, rate: 10, start_known: true, stale: false, cycles: 1},
    recent: [],
};

const api = {
    _version: 2,
    callable(name) {
        assert.equal(name, 'get_status');
        return async () => {
            if (fail)
                throw new Error('connection lost');
            return snapshot;
        };
    },
    addEventListener(name, callback) { listeners.set(name, callback); return callback; },
    removeEventListener(name, callback) {
        assert.equal(listeners.get(name), callback);
        listeners.delete(name);
    },
    toaster: {toast(value) { notifications.push(value); }},
};
globalThis.window = {
    __DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit: {
        connect(version, name) {
            assert.equal(version, 2);
            assert.equal(name, 'Steam Shaders');
            return api;
        },
    },
    setInterval(callback) { refresh = callback; return 42; },
    clearInterval(id) { assert.equal(id, 42); timerCleared = true; },
};
globalThis.SP_REACT = {
    useState(initial) {
        const index = cursor++;
        if (!(index in state))
            state[index] = initial;
        return [state[index], value => { state[index] = value; }];
    },
    useEffect(effect) {
        if (!mounted) {
            mounted = true;
            cleanup = effect();
        }
    },
};
const element = (type, props) => ({type, props});
globalThis.SP_JSX = {jsx: element, jsxs: element, Fragment: 'fragment'};
globalThis.DFL = {PanelSection: 'section', PanelSectionRow: 'row', staticClasses: {Title: 'title'}};

const plugin = (await import('../../build/decky/dist/index.js')).default();
function render() { cursor = 0; return plugin.content.type(); }
function text(node) {
    if (node == null)
        return '';
    if (Array.isArray(node))
        return node.map(text).join(' ');
    return typeof node === 'object' ? text(node.props?.children) : String(node);
}
const flush = () => new Promise(resolve => setImmediate(resolve));

assert.match(text(render()), /Iniciando monitor/);
await flush();
assert.match(text(render()), /Example Game/);
assert.match(text(render()), /62 %/);
assert.match(text(render()), /nesta etapa/);

snapshot = {...snapshot, status: 'finishing'};
refresh();
await flush();
assert.match(text(render()), /Confirmando conclusão/);
assert.doesNotMatch(text(render()), /Faltam/);

fail = true;
refresh();
await flush();
assert.match(text(render()), /Não foi possível consultar/);
assert.doesNotMatch(text(render()), /Example Game/);

fail = false;
snapshot = {...snapshot, status: 'idle', active: null};
refresh();
await flush();
assert.match(text(render()), /Nenhuma compilação/);

listeners.get('shaders_completed')('Example Game');
assert.match(notifications[0].body, /Example Game/);
cleanup();
plugin.onDismount();
assert.equal(listeners.size, 0);
assert.equal(timerCleared, true);
console.log('Decky frontend: loader connection, progress, completion, errors and cleanup passed.');
