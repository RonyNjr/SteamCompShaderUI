import deckyPlugin from '@decky/rollup';

const config = deckyPlugin();
config.input = './integrations/decky/index.tsx';
config.output.dir = './build/decky/dist';
// O plugin padrão limpa ./dist; esse diretório agora guarda o ZIP de distribuição.
config.plugins = config.plugins.filter(plugin => plugin.name !== 'delete');

export default config;
