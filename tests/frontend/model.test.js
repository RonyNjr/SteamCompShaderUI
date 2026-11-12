import {duration, historyLine, view} from '../../integrations/shared/model.js';

let count = 0;
function assert(condition, message) {
    if (!condition)
        throw new Error(message);
    count++;
}

const now = 1000;
const snapshot = {
    version: 1, updated_at: now, status: 'compiling',
    active: {
        name: 'Jogo de exemplo ®', percent: 62, stage: 2, done: 3213829, total: 3623167,
        elapsed_seconds: 7200, eta_seconds: 682, rate: 600,
        start_known: true, stale: false, cycles: 1,
    },
    recent: [],
};
const data = view(snapshot, now);
assert(data.visible, 'Compilação deve aparecer');
assert(data.label === '62%', 'Porcentagem original da Steam');
assert(data.detail === 'Etapa 2 de 3 · 62% no total', 'Etapa separada do progresso total');
assert(data.rows.some(row => row.includes('nesta etapa')), 'Estimativa tem escopo explícito');
assert(data.rows.some(row => row.includes('3.213.829')), 'Contadores em português');
assert(!view({...snapshot, status: 'idle', active: null}, now).visible, 'Ocioso fica oculto');
assert(!view(snapshot, now + 21).visible, 'Estado antigo do serviço fica oculto');
assert(!view(null, now).visible, 'Estado ausente fica oculto');
assert(!view({...snapshot, version: 2}, now).visible, 'Versão desconhecida fica oculta');
assert(!view({...snapshot, updated_at: now + 30}, now).visible, 'Relógio fora de sincronia fica oculto');
const finishing = view({...snapshot, status: 'finishing'}, now);
assert(finishing.label === '…', 'Não inventa 100% durante a confirmação');
assert(finishing.detail === 'Confirmando conclusão…', 'Explica a espera');
assert(!finishing.rows.some(row => row.includes('Faltam')), 'Conclusão não conserva estimativa');
const unknown = view({...snapshot, active: {...snapshot.active, percent: null, stage: null}}, now);
assert(unknown.label === '…' && unknown.percent === null, 'Sem log não inventa progresso');
const stale = view({...snapshot, active: {...snapshot.active, stale: true}}, now);
assert(!stale.rows.some(row => row.startsWith('Faltam')), 'Amostra velha não vira estimativa');
assert(stale.detail.includes('aguardando atualização'), 'Explica falta de atualização');
assert(duration(null) === '—', 'Tempo desconhecido não é zero');
assert(duration(682) === '11 min', 'Estimativa arredondada');
assert(duration(7200) === '2 h', 'Duração longa');
const history = historyLine({name: 'Jogo', outcome: 'interrupted', start_known: true,
    started_at: 1000, ended_at: 1120});
assert(history.includes('interrompido · 2 min'), 'Interrupção identificada no histórico');
const unknownStart = historyLine({name: 'Jogo', outcome: 'completed', start_known: false,
    started_at: 1000, ended_at: 1120});
assert(!unknownStart.includes('2 min'), 'Histórico não inventa duração completa');
print(`${count} verificações da apresentação passaram.`);
