# 💎 D.Ai OS: o computador que cresce com você

[English](../../README.md) · [עברית](../../README.md#בעברית) · [العربية](README.ar.md) · [Русский](README.ru.md) · [Español](README.es.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · **Português**

**Diga do que você precisa. Ele constrói, testa, corrige e pergunta antes de mudar qualquer coisa.**

🌐 **Site:** [rubinny.com](https://rubinny.com) · ⬇️ **Download:** [versão mais recente](https://github.com/diamondrubinny/D.Ai/releases/latest)

![A área de trabalho do D.Ai OS: uma barra de tarefas flutuante com o botão de diamante e um campo de comandos](../screenshots/desktop.png)

D.Ai OS é um sistema operacional gratuito e de código aberto baseado no Debian 13, criado por Diamond Rubinny (d.Ai). A inteligência artificial roda só no seu computador, e a segurança vem ligada desde a primeira inicialização.

## ✨ O que o torna diferente

- **🛠 Constrói o que você pede:** digite `+ um app para minha lista de compras` ou `+ instale um antivírus`. O D.Ai Forge escreve o app ou configura o recurso, e você revisa antes.
- **🧪 Testa o próprio trabalho:** cada app escrito pela IA roda primeiro em um ambiente isolado. Se ele travar, a IA o corrige a partir do erro e testa de novo.
- **🔭 Percebe o que está faltando:** um arquivo que nenhum programa abre, ou um comando que você digita todo dia. O D.Ai Evolve sugere construir a solução.
- **🩺 Conserta a si mesmo:** quando um programa trava, abre-se um chat que explica em palavras simples o que aconteceu e corrige com um clique, só com a sua aprovação.
- **🗣 Configuração com palavras:** "bloqueie pendrives e bloqueie a tela após 5 minutos" vira um plano que você pode revisar e desfazer.
- **🔒 Privacidade em primeiro lugar:** a IA roda localmente, e o serviço dela não tem acesso à rede. Sem telemetria, sem anúncios, sem nuvem.
- **🌍 Oito idiomas:** hebraico, inglês, árabe, russo, espanhol, francês, alemão e português: a interface, as frases que o D.Ai entende, o menu de inicialização e o site.
- **👁 Vê o ecrã e lê em voz alta:** `Super+Shift+E` (D.Ai Explain): o ecrã é lido no computador e, com um modelo de visão local (SmolVLM), o Diamond olha para a própria imagem e explica-a na tua língua, com um próximo passo seguro. `Super+Shift+S` (D.Ai Speak): o texto selecionado, uma página PDF, um e-mail ou a resposta do Diamond são lidos em voz alta em oito línguas, tudo neste computador (docs/EXPLAIN.md, docs/SPEAK.md).
- **🪟 A vir do Windows:** foco e modo de jogo numa frase, uma janela de definições com plano e desfazer, uma loja sem conta, o telemóvel por KDE Connect, procura dentro dos documentos, «o Firefox não vai à Internet», legendas ao vivo e poupança de memória (docs/BEYOND.md).
- **🎨 Bonito desde o primeiro segundo:** menu de inicialização do D.Ai, uma tela de carregamento em que o disco criptografado pede a frase-senha, uma tela de login do D.Ai e três temas (Noite, Dia e alto contraste).
- **📦 Apps próprios para o dia a dia:** J (e-mail assinado e criptografado, importa do Outlook), Ruby (navegador com proteção contra rastreamento e uBlock Origin), MOM (gerenciador de tarefas que mostra apps, não processos), D.Ai Quick e D.Ai Rescue (recupera o sistema pelo pendrive depois de uma atualização ruim).
- **📄 PDFs em uma caixa de areia:** o D.Ai PDF abre cada arquivo em um ambiente isolado, mostra o que o arquivo "quer" fazer (JavaScript, executar programas, enviar formulários) e nunca o faz; páginas, formulários, notas, uma assinatura carimbada, censura de verdade, OCR e um arquivo menor, tudo dentro da caixa de areia.
- **🪟 Windows em uma janela:** o D.Ai VM executa o Windows a partir da sua própria mídia de instalação e com a sua própria chave (KVM, UEFI com Secure Boot, TPM 2.0); pasta compartilhada, área de transferência e USB ficam desligados até você ligá-los. O D.Ai nunca distribui o Windows.
- **📺 Na TV, no celular, em ARM:** a edição tv inicia no Kodi em hebraico e é controlada pelo controle remoto; imagens arm64 experimentais do celular (Phosh) e da TV são construídas e iniciadas no QEMU na CI.

## 📸 Capturas de tela

| | | |
|---|---|---|
| ![Diamond responde a uma pergunta na barra de comandos](../screenshots/ai-answer.png) | ![D.Ai Quick: Wi-Fi, não perturbe, volume e nota de segurança](../screenshots/quick.png) | ![J, o cliente de e-mail](../screenshots/j.png) |
| **Diamond**: responde neste computador | **D.Ai Quick**: tudo o que é rápido, à mão | **J**: e-mail assinado e criptografado |
| ![O menu de inicialização pelo pendrive](../screenshots/boot-menu.png) | ![A tela de login](../screenshots/login.png) | ![D.Ai Welcome em árabe, da direita para a esquerda](../screenshots/welcome-ar.png) |
| **Menu de inicialização**: "Start D.Ai OS" | **Login**: a tela do D.Ai | **Welcome** em árabe, da direita para a esquerda |
| ![D.Ai TV: Kodi em hebraico em tela cheia](../screenshots/tv-desktop.png) | ![D.Ai Phone: a tela de bloqueio do Phosh em arm64](../screenshots/phone-lock.png) | ![D.Ai TV em arm64](../screenshots/tv-arm64.png) |
| **D.Ai TV**: Kodi em hebraico, nada escuta na rede | **D.Ai Phone** (experimental): Phosh em arm64, iniciado no QEMU | **D.Ai TV em arm64** (experimental): o mesmo Kodi, uma imagem UEFI genérica |
| ![D.Ai PDF: um arquivo aberto na caixa de areia, seu JavaScript e anexo listados na barra e nunca executados](../screenshots/pdf.png) | ![D.Ai VM: a verificação honesta do hardware e o que o Windows vê](../screenshots/vm.png) | |
| **D.Ai PDF**: o que o arquivo quer aparece na barra e nunca é feito | **D.Ai VM**: a verificação do hardware, e o que o Windows vê | |
| ![Definições D.Ai: a pontuação de segurança e depois cada definição como interruptor ou escolha](../screenshots/settings.png) | ![Loja D.Ai: as receitas por categoria e o que cada uma configura](../screenshots/store.png) | ![Legendas ao vivo D.Ai: o ficheiro de teste do whisper lido no computador](../screenshots/captions.png) |
| **Definições D.Ai**: uma janela, cada alteração com plano e desfazer | **Loja D.Ai**: encontrar e configurar software, sem conta | **Legendas D.Ai**: legendas para tudo o que o computador reproduz, no computador |

## ⚠️ Status

Versão alfa inicial. Experimente pelo pendrive antes de instalar. A interface, as frases que o D.Ai entende e o site estão disponíveis em português (e em mais sete idiomas).

**Licença:** Apache-2.0. "D.Ai", "D.Ai OS" e o logotipo de diamante são marcas registradas (`TRADEMARKS.md`).

> Esta é uma tradução. Correções de falantes nativos são bem-vindas via Pull Request.

© 2026 Diamond Rubinny (d.Ai)
