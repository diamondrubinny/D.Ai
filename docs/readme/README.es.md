# 💎 D.Ai OS: el ordenador que crece contigo

[English](../../README.md) · [עברית](../../README.md#בעברית) · [العربية](README.ar.md) · [Русский](README.ru.md) · **Español** · [Français](README.fr.md) · [Deutsch](README.de.md) · [Português](README.pt.md)

**Dile lo que necesitas. Lo construye, lo prueba, lo corrige y te pregunta antes de cambiar nada.**

🌐 **Sitio web:** [rubinny.com](https://rubinny.com) · ⬇️ **Descarga:** [última versión](https://github.com/diamondrubinny/D.Ai/releases/latest)

![El escritorio de D.Ai OS: una barra de tareas flotante con el botón del diamante y un campo de comandos](../screenshots/desktop.png)

D.Ai OS es un sistema operativo gratuito y de código abierto basado en Debian 13, creado por Diamond Rubinny (d.Ai). Su inteligencia artificial funciona solo en tu ordenador, y la seguridad está activada desde el primer arranque.

## ✨ Qué lo hace diferente

- **🛠 Construye lo que pides:** escribe `+ una app para mi lista de la compra` o `+ instala un antivirus`. D.Ai Forge escribe la app o configura la función, y tú la revisas antes.
- **🧪 Prueba su propio trabajo:** cada app que escribe la IA se ejecuta primero en un entorno aislado. Si falla, la IA la corrige a partir del error y vuelve a probarla.
- **🔭 Nota lo que te falta:** un archivo que ningún programa abre, o un comando que repites cada día. D.Ai Evolve te propone construir la solución.
- **🩺 Se repara sola:** cuando un programa falla, se abre un chat que explica lo ocurrido con palabras sencillas y lo arregla con un clic, solo si tú lo apruebas.
- **🗣 Configuración con palabras:** «bloquea las memorias USB y bloquea la pantalla tras 5 minutos» se convierte en un plan que puedes revisar y deshacer.
- **🔒 Privacidad ante todo:** la IA funciona en local y su servicio no tiene acceso a la red. Sin telemetría, sin anuncios, sin nube.
- **🌍 Ocho idiomas:** hebreo, inglés, árabe, ruso, español, francés, alemán y portugués: la interfaz, las frases que D.Ai entiende, el menú de arranque y el sitio web.
- **🪟 Viniendo de Windows:** enfoque y modo juego en una frase, una ventana de ajustes con plan y deshacer, una tienda sin cuenta, el teléfono por KDE Connect, búsqueda dentro de los documentos, «Firefox no sale a internet», subtítulos en vivo y ahorro de memoria (docs/BEYOND.md).
- **🎨 Bonito desde el primer segundo:** menú de arranque de D.Ai, una pantalla de carga donde el disco cifrado te pide su frase de contraseña, una pantalla de inicio de sesión de D.Ai y tres temas (Noche, Día y alto contraste).
- **📦 Apps propias para el día a día:** J (correo firmado y cifrado, importa desde Outlook), Ruby (navegador con protección contra el rastreo y uBlock Origin), MOM (administrador de tareas que muestra apps, no procesos), D.Ai Quick y D.Ai Rescue (recupera el sistema desde el USB tras una mala actualización).
- **📄 PDF en una caja de arena:** D.Ai PDF abre cada archivo en un entorno aislado, muestra lo que el archivo «quiere» hacer (JavaScript, ejecutar programas, enviar formularios) y nunca lo hace; páginas, formularios, notas, una firma estampada, censura real, OCR y un archivo más pequeño, todo dentro de la caja de arena.
- **🪟 Windows en una ventana:** D.Ai VM ejecuta Windows desde tu propio medio de instalación y con tu propia clave (KVM, UEFI con Secure Boot, TPM 2.0); la carpeta compartida, el portapapeles y el USB están apagados hasta que tú los enciendas. D.Ai nunca distribuye Windows.
- **📺 En la tele, en el teléfono, en ARM:** la edición tv arranca en Kodi en hebreo y se maneja con el mando; imágenes arm64 experimentales del teléfono (Phosh) y de la tele se construyen y arrancan en QEMU en la CI.

## 📸 Capturas de pantalla

| | | |
|---|---|---|
| ![Diamond responde una pregunta en la barra de comandos](../screenshots/ai-answer.png) | ![D.Ai Quick: Wi-Fi, no molestar, volumen y puntuación de seguridad](../screenshots/quick.png) | ![J, el cliente de correo](../screenshots/j.png) |
| **Diamond**: responde en este ordenador | **D.Ai Quick**: todo lo rápido, a mano | **J**: correo firmado y cifrado |
| ![El menú de arranque desde USB](../screenshots/boot-menu.png) | ![La pantalla de inicio de sesión](../screenshots/login.png) | ![D.Ai Welcome en árabe, de derecha a izquierda](../screenshots/welcome-ar.png) |
| **Menú de arranque**: «Start D.Ai OS» | **Inicio de sesión**: la pantalla de D.Ai | **Welcome** en árabe, de derecha a izquierda |
| ![D.Ai TV: Kodi en hebreo a pantalla completa](../screenshots/tv-desktop.png) | ![D.Ai Phone: la pantalla de bloqueo de Phosh en arm64](../screenshots/phone-lock.png) | ![D.Ai TV en arm64](../screenshots/tv-arm64.png) |
| **D.Ai TV**: Kodi en hebreo, nada escucha en la red | **D.Ai Phone** (experimental): Phosh en arm64, arrancado en QEMU | **D.Ai TV en arm64** (experimental): el mismo Kodi, una imagen UEFI genérica |
| ![D.Ai PDF: un archivo abierto en la caja de arena, su JavaScript y su adjunto listados en la barra y nunca ejecutados](../screenshots/pdf.png) | ![D.Ai VM: la comprobación honesta del hardware y lo que Windows ve](../screenshots/vm.png) | |
| **D.Ai PDF**: lo que el archivo quiere se muestra en la barra y nunca se hace | **D.Ai VM**: la comprobación del hardware, y lo que Windows ve | |
| ![Ajustes de D.Ai: la puntuación de seguridad y luego cada ajuste como interruptor o elección](../screenshots/settings.png) | ![Tienda D.Ai: las recetas por categoría y lo que configura cada una](../screenshots/store.png) | ![Subtítulos en vivo D.Ai: el archivo de prueba de whisper leído en el equipo](../screenshots/captions.png) |
| **Ajustes D.Ai**: una ventana, cada cambio con su plan y deshacer | **Tienda D.Ai**: encontrar y configurar software, sin cuenta | **Subtítulos D.Ai**: subtítulos para lo que reproduce el equipo, en el equipo |

## ⚠️ Estado

Versión alfa temprana. Pruébalo desde un USB antes de instalarlo. La interfaz, las frases que entiende D.Ai y el sitio web ya están disponibles en español (y en otros siete idiomas).

**Licencia:** Apache-2.0. «D.Ai», «D.Ai OS» y el logotipo del diamante son marcas registradas (`TRADEMARKS.md`).

> Esto es una traducción. Las correcciones de hablantes nativos son bienvenidas mediante Pull Request.

© 2026 Diamond Rubinny (d.Ai)
