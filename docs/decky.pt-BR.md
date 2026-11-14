# Steam Shaders no Decky Loader

[English](decky.md) · **Português do Brasil**

O plugin mostra o progresso no menu rápido do Decky, com jogo, porcentagem, etapa,
estimativa da etapa e os últimos processamentos. Uma notificação do Decky confirma a conclusão.
A interface usa português do Brasil nesta versão.

**Situação:** versão experimental. O frontend compila, o backend é testado com a API do Decky
simulada, e a API e os módulos Python usados foram conferidos no Decky Loader 3.3.1.
Ainda não houve validação em um Steam Deck real. O plugin não está na loja do Decky.

## Instalar pela URL

Este método funciona depois que houver uma release publicada no GitHub.

1. No Decky, abra **Configurações › Geral** e ative o **modo desenvolvedor**.
2. Em **Configurações › Desenvolvedor**, procure **Instalar Plugin a partir da URL**.
3. Informe o endereço abaixo e toque em **Instalar**:

   ```text
   https://github.com/RonyNjr/SteamCompShaderUI/releases/latest/download/steam-shaders.zip
   ```

4. Abra **Steam Shaders** no menu de plugins. A detecção e a leitura começam automaticamente.

Para atualizar, repita a instalação com o mesmo endereço, que sempre aponta para a release
mais recente.

## Instalar por arquivo ZIP

1. Baixe `steam-shaders.zip` na página de [releases](https://github.com/RonyNjr/SteamCompShaderUI/releases)
   ou gere o pacote localmente, como descrito em [Compilar](#compilar).
2. Com o modo desenvolvedor ativo, use **Instalar Plugin a partir de um arquivo ZIP**
   e selecione o arquivo.

Não é preciso instalar o serviço do desktop, GNOME, Node.js ou pacotes Python no Steam Deck.
O monitor é incluído no ZIP e roda no backend Python já oferecido pelo Decky.
O plugin não usa a flag `_root`, não inicia comandos externos e não baixa dados da internet.
Ele não altera arquivos da Steam nem cancela compilações.

Ao desabilitar ou remover o plugin, seu monitor encerra. O código não apaga o histórico;
o gerenciamento dos diretórios do plugin continua pertencendo ao Decky.
A instalação desktop e o plugin guardam históricos separados. Se usar ambos, desative
notificações em um deles para evitar avisos duplicados.

## Compilar

Na pasta do repositório, com Python 3.9+, Node.js 22+ e pnpm **9** instalados:

```sh
pnpm install --frozen-lockfile
pnpm run typecheck
pnpm run build
pnpm test
pnpm run package
```

Se o pnpm não estiver disponível, é possível executar cada comando com
`npx --yes pnpm@9.15.9` no lugar de `pnpm`, sem instalar ferramentas globalmente.
Essas ferramentas são usadas apenas no desenvolvimento.

O pacote fica em `dist/steam-shaders-0.2.0.zip`:

```text
steam-shaders/
  plugin.json
  package.json
  main.py
  dist/index.js
  py_modules/steam_shaders/monitor.py
  py_modules/steam_shaders/support.py
  py_modules/steam_shaders/decky.py
  README.md
  LICENSE
```

O build copia o pacote `steam_shaders/` para a área temporária `build/decky/`.
O frontend também usa `integrations/shared/model.js` para apresentar as mesmas informações do GNOME.
Não há uma segunda implementação do parser de logs.

Os arquivos de runtime ficam em `build/decky/dist/`, `build/decky/py_modules/` e
`build/decky/vendor/`. O empacotador os coloca nos caminhos esperados pelo Decky dentro do ZIP.
O ZIP inclui também os fontes e as licenças necessários para reconstruir a interface;
testes, extensão GNOME e instalador desktop ficam de fora.

## Configuração e diagnóstico

O backend usa `DECKY_PLUGIN_RUNTIME_DIR` para estado, cursor e histórico. A configuração
opcional fica em `DECKY_PLUGIN_SETTINGS_DIR/config.json`; os diretórios exatos são definidos
pelo próprio Decky, sem assumir que o usuário se chama `deck`.

```json
{
  "steam_dir": "/caminho/absoluto/da/Steam",
  "notifications": false
}
```

Omita `steam_dir` para detecção automática. Omita `notifications` para receber avisos.
Recarregue o plugin depois de editar a configuração. Falhas do backend aparecem no log do
plugin mantido pelo Decky. Ausência de `shader_log.txt` pode significar que o pré-cache ainda
não gerou atividade; confira também as configurações da Steam.

## Validação no aparelho

Antes de tratar esta versão como estável, precisamos registrar:

- SteamOS e Decky usados no teste, nos canais Stable e Beta.
- Aparição de jogo e progresso durante uma compilação real, com navegação pelo controle.
- Notificação após conclusão confirmada; ausência de aviso de sucesso em interrupções.
- Recarregamento e desativação do plugin encerrando o monitor, sem processos abandonados.
- Comportamento ao suspender/retomar o Steam Deck, abrir um jogo e fechar a Steam.

As verificações automatizadas não substituem esses testes. Uma imagem real da interface no
Decky também deve ser capturada antes de preparar uma apresentação para a loja.

## Restrição atual da loja

Consultado em **12/11/2026**: o [formulário oficial para novos plugins](https://github.com/SteamDeckHomebrew/decky-plugin-database/blob/main/.github/PULL_REQUEST_TEMPLATE/plugin_addition.md)
exige declarar que a maior parte do código enviado não foi escrita por IA generativa.
Este projeto foi desenvolvido com assistência de IA e não pode fazer essa declaração
honestamente no estado atual. Por isso, a distribuição é feita pelas releases do GitHub,
instaladas pela URL ou pelo ZIP; o projeto não está pronto para um envio elegível à loja.

O mesmo formulário pede validação pelo autor em SteamOS Stable e Beta e prevê teste de
terceiros. O [repositório da loja](https://github.com/SteamDeckHomebrew/decky-plugin-database)
explica o envio por pull request. Caso a política mude ou os mantenedores esclareçam uma
forma de participação aplicável ao projeto, a elegibilidade deve ser reavaliada sem omitir
como o código foi produzido.

Referências de implementação: [template oficial](https://github.com/SteamDeckHomebrew/decky-plugin-template),
[API e caminhos Python do Decky](https://github.com/SteamDeckHomebrew/decky-loader/blob/main/backend/decky_loader/plugin/imports/decky.py)
e [API do frontend](https://github.com/SteamDeckHomebrew/decky-frontend-lib).
