export interface Session {
    id?: string;
    appid?: string | null;
    name: string;
    outcome?: string;
    start_known: boolean;
    started_at: number;
    ended_at: number;
}

export interface Snapshot {
    version: number;
    updated_at: number;
    status: string;
    active: (Omit<Session, 'ended_at' | 'outcome'> & {
        percent: number | null;
        stage: number | null;
        done: number | null;
        total: number | null;
        elapsed_seconds: number;
        eta_seconds: number | null;
        rate: number | null;
        stale: boolean;
        cycles: number;
    }) | null;
    recent?: Session[];
    error?: string;
    steam_found?: boolean;
    log_available?: boolean;
}

export function duration(seconds: number | null): string;
export function historyLine(row: Session): string;
export function view(snapshot: Snapshot | null, now?: number): {
    visible: boolean;
    name?: string;
    percent?: number | null;
    label?: string;
    detail?: string;
    rows?: string[];
    recent?: Session[];
};
