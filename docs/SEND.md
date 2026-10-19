# Encrypted messages and pictures between D.Ai computers: plan for approval

> Written on 2026-10-19 after "sending encrypted messages and pictures between computers with the operating system". **Plan only: no code until the decisions in §8 are made.** The working name "D.Ai Link" **requires a trademark check.** The protocol **requires an external security review** before release.

## 1. What I understood

- **The need:** two (or more) people with D.Ai OS send each other text messages and pictures, **encrypted end to end**. Only the two computers can read them, not the network, not a server, and not us.
- **Values that do not change:** privacy (nothing goes through us), no account, and safety (a picture from someone else must not hurt the computer).

## 2. Three ways to build it (and a recommendation)

| | A. Local network, no server (**recommended for stage 1**) | B. Over the internet with a code, through a public relay | C. Ongoing chat over the internet (Matrix) |
|---|---|---|---|
| How | The computers find each other on the same Wi-Fi (Avahi, already on the image) and talk directly | Magic Wormhole (in Debian): the sender gets a short code ("7-crystal-river") and the recipient types it. A relay passes ciphertext it cannot read | A Matrix account on an existing server (or your own) and E2E encryption (Olm/Megolm); the client is nheko (Qt, in Debian) |
| Encryption | libsodium (PyNaCl, in Debian): X25519, XChaCha20-Poly1305, Ed25519 signatures | SPAKE2 plus NaCl, a well-reviewed protocol | Olm/Megolm, well reviewed |
| Server | None | The relay of the Magic Wormhole project (or our own later). It sees IP addresses and file sizes, never content | The Matrix server sees metadata (who talks to whom and when), not content |
| Account | None | None | Required |
| Range | The same network (home, office, school) | Anywhere, one transfer at a time | Anywhere, continuous |
| Risk / cost | Our protocol needs a security review | Low: a ready-made protocol, our own interface | Medium: a heavy app, metadata on a server |

**Recommendation:**
1. **Stage 1 = A**, the local network: messages, pictures, and a chat window.
2. **Stage 2 = B**, sending a picture or file over the internet with a code.
3. **C** only on request, as a Forge recipe ("+ secure chat"), not built into D.Ai.

**What not to do: a central D.Ai server.** It would hold metadata about our users, cost money to run, carry legal obligations (data protection, lawful-access requests) and handle abuse. That contradicts "nothing goes through us".

## 3. Stage 1 in detail (A)

### The experience

- **Pairing, once per contact:**
  - On both computers: "+ pair with a computer", or the button in the window.
  - Both screens show **the same 6 symbols** (diamond emojis plus words in the interface language).
  - Both people confirm they match. That is the protection against an impostor (MITM).
- **Sending:**
  - A chat window like a messaging app: text, a picture (drag and drop, or paste from the clipboard), and "seen".
  - From the command field: `send Dana: hi, I'm coming` or `שלח לדנה: היי, אני מגיע`.
  - From the file manager: right-click a picture, then "Send with D.Ai Link".
- **Receiving:** a notification with a sound (`message-new-instant` from the diamond family) and the sender's name, not the content when the screen is locked.
- **Unknown sender:** not received. Only paired contacts can send.

### Encryption (proposal, for external review)

- **Identity:** an Ed25519 key per user, created on the first run. The private key is encrypted in the keyring (gnome-keyring, which is already on the image), as in J.
- **Each conversation:**
  - Each side creates a temporary X25519 key and signs it with its identity key. They exchange them, and both derive keys with HKDF (BLAKE2b).
  - **Forward secrecy:** after the conversation, its keys are erased.
  - Messages use XChaCha20-Poly1305 with a counter, so a message cannot be repeated or reordered.
- **Pairing:** the symbols come from a hash of both identity keys (SAS), as in Signal's safety number.
- **What we do not invent:** we use only libsodium primitives through PyNaCl. Building the protocol from them is still our own design, so **a review by a security expert is required before release**.

### Pictures

- **Before sending:**
  - The location (GPS) and the rest of the EXIF data are stripped.
  - The picture is shrunk to a reasonable size (an option "send the original"), and its MIME type is checked.
- **On receiving:**
  - **Size limit:** 25 MB.
  - **Allowed types:** PNG, JPEG, WebP.
  - **Decoding and re-saving in a bubblewrap sandbox** with no network and no home folder, as in Forge. A malicious picture does not reach the system.
  - **Antivirus:** a ClamAV scan when it is installed. Anything suspicious stays in quarantine, with a clear message.

### Network and firewall

- **Discovery:** an Avahi service (`_dai-link._tcp`) on the local network only. It advertises only "a D.Ai Link exists" and a random identifier, without a name. The name is exchanged only after pairing.
- **The port:**
  - Opened in the firewall **only for the local network** (the `lan` source that Tune already knows), and only while D.Ai Link is on.
  - Turning it on goes through D.Ai Tune, with a plan and undo.
- **Rate limit** for connection attempts.

### Storage and privacy

- History is kept only on the computer (`~/.local/share/dai/link`, 0600, encrypted disk). An option: "delete messages after N days", with a default that still needs deciding.
- **Nothing goes to us or to any third party.** There is no account and no server.
- **Rights:** deleting a conversation deletes it from your computer only, not from the other person's. That is stated in the interface.
- **The education edition:** off by default, and the organization chooses (policy), because of minors. **This requires legal review.**

## 4. Threat model (short)

| Asset | Threat | Control |
|-------|--------|---------|
| Message content | Eavesdropping on Wi-Fi (a café, an office) | End-to-end encryption; nothing in clear text on the network |
| The identity of the other side | An impostor on the network (MITM) | Pairing with 6 symbols compared by people; signed ephemeral keys |
| The computer | A malicious picture | Size and type limits, sandboxed decoding, ClamAV, quarantine |
| Privacy | GPS in a picture, a name advertised on the network | EXIF stripping; discovery without names; only paired contacts |
| Availability | Message flooding | Only paired contacts; a rate limit; an option to block a contact |
| Keys | Theft of the computer | The identity key in the keyring, the disk encrypted (LUKS) |
| Past messages | A key stolen in the future | Ephemeral keys per conversation (forward secrecy) |

## 5. Stage 2 (B): over the internet with a code

- "Send this picture over the internet": you get a code of 3 words and give it to the other person (by phone, in person). They type it, and the picture arrives, encrypted end to end.
- Through `magic-wormhole` (in Debian), with the project's public relay. **Its privacy terms require checking**, and running our own relay later is an option.
- The same picture checks as in stage 1.

## 6. Work plan (after approval)

1. **The core:**
   - keys, the handshake, encryption and the message format;
   - tests: the known vectors of libsodium, impostor and replay tests.
2. **The network:** discovery, a connection limited to the local network, and the firewall through Tune. Then a test between two VMs in CI (two QEMUs on one network).
3. **Pairing:** with the symbols, plus a test.
4. **The chat window:** Qt, RTL, accessible (Raz checks it in three themes). Pictures with a sandbox.
5. **The command field and the file manager**, and notifications with sound.
6. **Documentation, privacy (a draft for legal review), and an external security review.**

## 7. Not included (stage 1)

- Groups.
- Voice and video calls.
- Sync between your own computers.
- Messages to phones.

Each of these could come later.

## 8. Decisions needed from you

1. **Scope:** local network first (recommended), or the internet from day one (stage B in parallel)?
2. **What to send in stage 1:** text and pictures (recommended), or also any file, or also voice messages?
3. **The name:** "D.Ai Link", "Diamond Chat", or something else? It needs a trademark check.
4. **Message history:** keep it until deleted (recommended, like a messaging app), or delete automatically after 30 days?

---

© 2026 Diamond Rubinny (d.Ai) · D.Ai OS · Apache-2.0
