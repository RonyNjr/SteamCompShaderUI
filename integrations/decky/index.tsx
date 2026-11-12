import {PanelSection, PanelSectionRow, staticClasses} from '@decky/ui';
import {addEventListener, callable, definePlugin, removeEventListener, toaster} from '@decky/api';
import {useEffect, useState} from 'react';
import {historyLine, view, type Snapshot} from '../shared/model.js';

const getStatus = callable<[], Snapshot>('get_status');

function Content() {
    const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
    const [failure, setFailure] = useState(false);
    useEffect(() => {
        let disposed = false;
        let loading = false;
        const refresh = async () => {
            if (loading)
                return;
            loading = true;
            try {
                const state = await getStatus();
                if (!disposed) {
                    setSnapshot(state);
                    setFailure(false);
                }
            } catch {
                if (!disposed)
                    setFailure(true);
            } finally {
                loading = false;
            }
        };
        void refresh();
        const timer = window.setInterval(() => void refresh(), 2000);
        return () => {
            disposed = true;
            window.clearInterval(timer);
        };
    }, []);
    const data = view(snapshot);
    let message = 'Nenhuma compilação de shaders em andamento.';
    if (!snapshot)
        message = 'Iniciando monitor…';
    else if (snapshot.steam_found === false)
        message = 'Steam ainda não encontrada. Abra a Steam e aguarde a detecção.';
    else if (snapshot.log_available === false)
        message = 'Aguardando o log de shaders. Confira o pré-cache nas configurações da Steam.';
    if (failure || snapshot?.error)
        message = snapshot?.error ?? 'Não foi possível consultar o monitor. Recarregue o plugin no Decky.';
    const recent = data.recent ?? snapshot?.recent?.slice(0, 3) ?? [];
    return <>
        <PanelSection title="Compilação de shaders">
            {data.visible && !failure && !snapshot?.error ? <>
                <PanelSectionRow><strong>{data.name}</strong></PanelSectionRow>
                {data.percent != null && <PanelSectionRow>
                    <progress aria-label="Progresso informado pela Steam" max={100}
                        value={data.percent} style={{width: '100%'}} />
                    <span>{data.percent}%</span>
                </PanelSectionRow>}
                <PanelSectionRow><span>{data.detail}</span></PanelSectionRow>
                {data.rows?.map(row => <PanelSectionRow key={row}><span>{row}</span></PanelSectionRow>)}
            </> : <PanelSectionRow><span role="status">{message}</span></PanelSectionRow>}
        </PanelSection>
        {recent.length > 0 && <PanelSection title="Últimos processamentos">
            {recent.map((row, index) => <PanelSectionRow key={row.id ?? index}>
                <span style={{whiteSpace: 'pre-line'}}>{historyLine(row)}</span>
            </PanelSectionRow>)}
        </PanelSection>}
    </>;
}

export default definePlugin(() => {
    const listener = addEventListener<[name: string]>('shaders_completed', name => {
        toaster.toast({title: 'Shaders concluídos', body: `Processamento de shaders de ${name} concluído.`});
    });
    return {
        name: 'Steam Shaders',
        titleView: <div className={staticClasses.Title}>Steam Shaders</div>,
        icon: <svg viewBox="0 0 16 16" width="1em" height="1em" aria-hidden="true"
            fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3.5" y="3.5" width="9" height="9" rx="1" />
            <path d="M5.5 1v2m5-2v2m-5 10v2m5-2v2M1 5.5h2m-2 5h2m10-5h2m-2 5h2M8.5 5.5l-2 3h3l-2 2" />
        </svg>,
        content: <Content />,
        onDismount() {
            removeEventListener('shaders_completed', listener);
        },
    };
});
