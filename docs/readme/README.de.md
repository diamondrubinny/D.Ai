# 💎 D.Ai OS: der Computer, der mit dir wächst

[English](../../README.md) · [עברית](../../README.md#בעברית) · [العربية](README.ar.md) · [Русский](README.ru.md) · [Español](README.es.md) · [Français](README.fr.md) · **Deutsch** · [Português](README.pt.md)

**Sag ihm, was du brauchst. Es baut es, testet es, repariert es und fragt dich, bevor es etwas ändert.**

🌐 **Website:** [rubinny.com](https://rubinny.com) · ⬇️ **Download:** [neueste Version](https://github.com/diamondrubinny/D.Ai/releases/latest)

![Der D.Ai-OS-Desktop: eine schwebende Taskleiste mit dem Diamant-Knopf und einem Befehlsfeld](../screenshots/desktop.png)

D.Ai OS ist ein freies Open-Source-Betriebssystem auf Basis von Debian 13, entwickelt von Diamond Rubinny (d.Ai). Die KI läuft nur auf deinem eigenen Computer, und die Sicherheit ist ab dem ersten Start eingeschaltet.

## ✨ Was es besonders macht

- **🛠 Es baut, worum du bittest:** schreib `+ eine App für meine Einkaufsliste` oder `+ installiere einen Virenscanner`. D.Ai Forge schreibt die App oder richtet die Funktion ein, und du prüfst zuerst.
- **🧪 Es testet seine eigene Arbeit:** jede App, die die KI schreibt, startet zuerst in einer abgeschotteten Sandbox. Stürzt sie ab, repariert die KI sie anhand der Fehlermeldung und testet erneut.
- **🔭 Es bemerkt, was dir fehlt:** eine Datei, die kein Programm öffnet, oder ein Befehl, den du jeden Tag tippst. D.Ai Evolve schlägt vor, die Lösung zu bauen.
- **🩺 Es repariert sich selbst:** stürzt ein Programm ab, öffnet sich ein Chat, der in einfachen Worten erklärt, was passiert ist, und es mit einem Klick behebt, nur mit deiner Zustimmung.
- **🗣 Einstellungen in Worten:** „sperre USB-Sticks und sperre den Bildschirm nach 5 Minuten“ wird zu einem Plan, den du prüfen und rückgängig machen kannst.
- **🔒 Privatsphäre zuerst:** die KI läuft lokal, und ihr Dienst hat keinen Netzwerkzugang. Keine Telemetrie, keine Werbung, keine Cloud.
- **🌍 Acht Sprachen:** Hebräisch, Englisch, Arabisch, Russisch, Spanisch, Französisch, Deutsch und Portugiesisch: die Oberfläche, die Sätze, die D.Ai versteht, das Startmenü und die Website.
- **🎨 Schön ab der ersten Sekunde:** ein D.Ai-Startmenü, ein Ladebildschirm, auf dem die verschlüsselte Festplatte nach ihrer Passphrase fragt, ein D.Ai-Anmeldebildschirm und drei Designs (Nacht, Tag und hoher Kontrast).
- **📦 Eigene Apps für jeden Tag:** J (Mail, signiert und verschlüsselt, Import aus Outlook), Ruby (Browser mit Tracking-Schutz und uBlock Origin), MOM (Task-Manager, der Apps statt Prozesse zeigt), D.Ai Quick und D.Ai Rescue (holt das System nach einem missglückten Update vom USB-Stick aus zurück).
- **📄 PDFs in der Sandbox:** D.Ai PDF öffnet jede Datei in einer Sandbox, zeigt, was die Datei „will“ (JavaScript, Programme starten, Formulare senden), und tut es nie; Seiten, Formulare, Notizen, eine Stempel-Unterschrift, echtes Schwärzen, OCR und eine kleinere Datei, alles in der Sandbox.
- **🪟 Windows im Fenster:** D.Ai VM startet Windows von deinem eigenen Installationsmedium mit deinem eigenen Schlüssel (KVM, UEFI mit Secure Boot, TPM 2.0); gemeinsamer Ordner, Zwischenablage und USB bleiben aus, bis du sie einschaltest. D.Ai liefert kein Windows mit.
- **📺 Am Fernseher, am Telefon, auf ARM:** die Edition tv startet in Kodi auf Hebräisch und wird mit der Fernbedienung gesteuert; experimentelle arm64-Abbilder des Telefons (Phosh) und des Fernsehers werden in der CI gebaut und in QEMU gestartet.

## 📸 Screenshots

| | | |
|---|---|---|
| ![Diamond beantwortet eine Frage in der Befehlsleiste](../screenshots/ai-answer.png) | ![D.Ai Quick: WLAN, Nicht stören, Lautstärke und Sicherheitswert](../screenshots/quick.png) | ![J, das Mailprogramm](../screenshots/j.png) |
| **Diamond**: antwortet auf diesem Computer | **D.Ai Quick**: alles Schnelle an einem Ort | **J**: Mail, signiert und verschlüsselt |
| ![Das Startmenü vom USB-Stick](../screenshots/boot-menu.png) | ![Der Anmeldebildschirm](../screenshots/login.png) | ![D.Ai Welcome auf Arabisch, von rechts nach links](../screenshots/welcome-ar.png) |
| **Startmenü**: „Start D.Ai OS“ | **Anmeldung**: der D.Ai-Anmeldebildschirm | **Welcome** auf Arabisch, von rechts nach links |
| ![D.Ai TV: Kodi auf Hebräisch im Vollbild](../screenshots/tv-desktop.png) | ![D.Ai Phone: der Sperrbildschirm von Phosh auf arm64](../screenshots/phone-lock.png) | ![D.Ai TV auf arm64](../screenshots/tv-arm64.png) |
| **D.Ai TV**: Kodi auf Hebräisch, nichts lauscht im Netz | **D.Ai Phone** (experimentell): Phosh auf arm64, in QEMU gestartet | **D.Ai TV auf arm64** (experimentell): dasselbe Kodi, ein generisches UEFI-Abbild |

## ⚠️ Status

Frühe Alpha-Version. Probiere es vor der Installation vom USB-Stick aus. Die Oberfläche, die Sätze, die D.Ai versteht, und die Website gibt es auf Deutsch (und in sieben weiteren Sprachen).

**Lizenz:** Apache-2.0. „D.Ai“, „D.Ai OS“ und das Diamant-Logo sind Marken (`TRADEMARKS.md`).

> Dies ist eine Übersetzung. Korrekturen von Muttersprachlern sind per Pull Request willkommen.

© 2026 Diamond Rubinny (d.Ai)
