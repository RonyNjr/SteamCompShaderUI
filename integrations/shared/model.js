// Funções puras: o mesmo formato é usado no painel e no menu.
export function duration(seconds) {
    if (!Number.isFinite(seconds) || seconds < 0)
        return '—';
    if (seconds < 60)
        return `${Math.max(1, Math.round(seconds))} s`;
    const minutes = Math.round(seconds / 60);
    if (minutes < 60)
        return `${minutes} min`;
    const hours = Math.floor(minutes / 60);
    return `${hours} h${minutes % 60 ? ` ${minutes % 60} min` : ''}`;
}

function number(value) {
    return new Intl.NumberFormat('pt-BR').format(Math.round(value));
}

export function view(snapshot, now = Date.now() / 1000) {
    const job = snapshot?.active;
    if (snapshot?.version !== 1 || !Number.isFinite(snapshot.updated_at) ||
        now - snapshot.updated_at > 20 || now < snapshot.updated_at - 5 || !job ||
        !['compiling', 'finishing'].includes(snapshot.status))
        return {visible: false};

    const percent = Number.isFinite(job.percent)
        ? Math.max(0, Math.min(100, job.percent)) : null;
    const finishing = snapshot.status === 'finishing';
    let detail = 'Aguardando informações de progresso da Steam…';
    if (finishing)
        detail = 'Confirmando conclusão…';
    else if (job.stale)
        detail = 'Processamento detectado; aguardando atualização do log…';
    else if (Number.isFinite(job.stage))
        detail = `Etapa ${job.stage} de 3 · ${percent}% no total`;

    const rows = [];
    if (Number.isFinite(job.done) && Number.isFinite(job.total))
        rows.push(`${number(job.done)} / ${number(job.total)} pipelines nesta etapa`);
    rows.push(`${job.start_known ? 'Tempo decorrido' : 'Acompanhando há'}: ${duration(job.elapsed_seconds)}`);
    if (!finishing) {
        if (Number.isFinite(job.rate) && job.rate > 0 && !job.stale)
            rows.push(`Velocidade: ~${number(job.rate)} pipelines/s`);
        rows.push(Number.isFinite(job.eta_seconds) && !job.stale
            ? `Faltam ~${duration(job.eta_seconds)} nesta etapa`
            : 'Estimativa desta etapa: aguardando amostras');
    }
    if (job.cycles > 1)
        rows.push(`${job.cycles} processamentos consecutivos deste jogo`);
    return {
        visible: true,
        name: typeof job.name === 'string' ? job.name : 'Jogo não identificado',
        percent,
        label: finishing ? '…' : percent === null ? '…' : `${percent}%`,
        detail,
        rows,
        finishing,
        recent: Array.isArray(snapshot.recent) ? snapshot.recent.slice(0, 3) : [],
    };
}

export function historyLine(row) {
    const outcome = row.outcome === 'completed' ? 'concluído' : 'interrompido';
    const elapsed = row.start_known ? ` · ${duration(row.ended_at - row.started_at)}` : '';
    const when = new Date(row.ended_at * 1000).toLocaleString('pt-BR', {
        day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
    });
    return `${row.name} — ${outcome}${elapsed}\n${when}`;
}
