# Diamond Chat: encrypted messages and pictures between D.Ai computers

> Written on 2026-10-19 after "sending encrypted messages and pictures between computers with the operating system".
> **Approved:**
> - **The name:** Diamond Chat. **It requires a trademark check.**
> - **Scope:** the internet from day one, through Tor onion services. The local network directly.
> - **Content:** text and pictures.
> - **History:** kept until deleted.
>
> - **Added (19 October 2026):**
>   - each person is shown by a **display name** they choose, never by the computer's user name;
>   - **receiving is off by default**: until the person turns it on, nobody can reach them (their messages wait on the senders' computers);
>   - **the person must choose**: messages from a new contact wait as a request until accepted or declined;
>   - **every received message is checked first** for phishing and malware, and a suspicious one is held even from an accepted contact.
>
> The protocol **requires an external security review** before release.

## 0. The approved architecture (replaces the options in §2)

- **Two ways to reach a contact, with the same protocol and the same encryption on top:**
  1. **The same network:** directly over TCP, found with mDNS (python3-zeroconf). Fast.
  2. **The internet:** through a **Tor onion service**, as Briar, Cwtch and OnionShare do.
     - Every computer is reachable at a private `.onion` address.
     - No server, no account, and no IP address shown to anyone.
     - Tor (`tor`, in Debian) runs as a user service only while Chat is on.
     - The onion key is kept like the identity key, so the address stays the same.
- **Order:** the local network is tried first, then Tor. A message to a contact who is not online waits in a queue on the sender's computer and goes out when they come online. Messages are never kept on a third party.
- **Pairing over the internet:**
  - An invitation code (base32: the onion address and a fingerprint of the identity key) is given out of band: by phone, in person, or as a QR code.
  - Then the 6 symbols are compared, by phone or in a video call. Without that comparison the contact is marked "unverified", in orange, and no picture is received from them.
- **Our own encryption runs above Tor's.** Tor protects the metadata (who talks to whom). Our end-to-end encryption protects the content even on the local network.
- **The core** (`apps/dai-chat/dai_chat`): `keys` (identity, storage), `session` (signed handshake, keys with HKDF-BLAKE2b, XChaCha20-Poly1305 with counters, no replays), `sas` (the 6 symbols), `store` (SQLite 0600), `pictures` (stripping and sandboxed decoding), then `transport` (TCP/Tor) and `gui`.

## Status

- **Stage 1, the core:** built (`apps/dai-chat/dai_chat`):
  - `keys`: identity in the keyring, a 0600 file only when there is no keyring;
  - `session`: signed handshake, XChaCha20-Poly1305 with counters;
  - `sas`: 6 symbols out of 64;
  - `invite`: an invitation code with a checksum, canonical only;
  - `message`: text, picture, receipt, with checks;
  - `store`: SQLite 0600, a queue for offline contacts, deleting a conversation.
- **The core's tests (23):**
  - an impostor in the middle, a HELLO sent to someone else, an old reply;
  - a weak key (low order);
  - an altered message, a replayed message, a message out of order, a reflected message;
  - a typo at any position of the invitation;
  - a picture that is not what it claims to be, SVG refused, a path in the message id;
  - the seed never on a command line.
- **Stage 2, the connection:** built.
  - `transport`: the same exchange over the local network (TCP, port 7714) and over Tor (SOCKS5 on a Unix socket, `.onion` names only).
    - Both sides send their queues at the same time, receipts come back, then BYE.
    - Only known contacts get through. Pictures only from a contact whose symbols were compared.
    - A receipt changes only a message sent to the person who sends it.
    - A few handshakes a minute per address.
  - `tor`: the person's own Tor, not a system service.
    - The sockets are in a 0700 folder, with cookie authentication; Tor exits with Chat.
    - The onion key is kept like the identity key and given to Tor over the control socket, so the address stays the same. The address Tor returns is checked against the key.
    - Tested against a real Tor 0.4.9.
  - `discovery`: mDNS with a random name and a tag that changes every hour, keyed by the code's fingerprint. Contacts find each other; strangers cannot follow a computer. Tested with two real announcers.
  - `pairing`: each person types the other's code; the computers swap full keys with signatures, and each checks them against the code it typed (as Briar does). Contacts stay "not verified" until the six symbols are compared.
  - `service` and `cli`: the user service `dai-chat.service` is off until `dai-chat on`. It tries every half minute (sooner when poked), the local network first and then Tor, waiting up to 15 minutes after failures. A notification names the sender, never the message.
  - Commands: `dai-chat code | add | contacts | symbols | verify | send | read | delete | block | lan | on | off | status`.
- **Pictures (`pictures`):** built. Every picture, sent or received, is decoded and encoded again as new pixels.
  - Decoding runs in bubblewrap: no network, no home folder, read-only /usr, with limits on memory and time.
  - The reader is the one for the type the first bytes say (PNG, JPEG, WebP), never SVG or PDF.
  - Location, camera, date and thumbnail are removed. Anything hidden after the picture is dropped.
  - Long side at most 4096 pixels. A decompression bomb is refused.
  - When the ClamAV daemon is installed, it scans first. `dai-chat send-picture NAME FILE` only to verified contacts.
- **The window (`gui`, `dai-chat window`, "Diamond Chat" in the menu):** built.
  - Contacts and codes still waiting on one side, the conversation on the other, the message field at the bottom.
  - Each message is laid out in its own direction: Hebrew right to left even in an English window, and the reverse.
  - Theirs at the start of the line, mine at the end, with ⌛ / ✓ / ✓✓.
  - Adding a contact shows your code too. The symbols are shown large, with "They match" / "They are different".
  - Pictures only to verified contacts, re-drawn before they are queued.
  - Passes Raz's accessibility audit in Hebrew and English, in all three themes.
  - Pictures show as a thumbnail (with "[a picture]" for screen readers); Enter or a double click opens them.
- **The local network (`dai-chat lan on|off`):** through D.Ai Tune, "open port 7714 and open udp port 5353" (Chat, and mDNS so contacts find each other), to the local network only. Tune shows a plan and asks for confirmation (it weakens the firewall), with undo. If the firewall was not changed, Chat stays on Tor only.
- **From the command field (D.Ai Command):** "send Dana: see you at six" / "שלח לדנה: מגיעה בשש" offers sending to a contact. The message is queued inside the command bar's own process, never on another program's command line (visible in `ps`), and is not kept in the bar's history.
- **Display name, receiving, requests and checks (the 19 October decisions):** built.
  - `dai-chat name NAME` / in the window on first use: the name contacts see, sent signed when pairing, cleaned of control and direction characters (no spoofing), at most 40 characters. A code cannot be given out before a name is chosen. The contact appears under the name you gave them, with "calls themselves: …".
  - `dai-chat receive on|off` / the "Receiving" switch, **off by default**. While off: no listening port, no onion service published, no announcement on the local network; senders get "deferred" and keep the message queued, retrying later.
  - **Requests:** messages from a contact you have not accepted are not shown; the window shows "Dana sent 2 messages" with **Accept** / **Decline and block**; declining deletes them.
  - **Checks (`scan`), on this computer only:** links that pretend to be a known site (including Israeli banks, with look-alike letters decoded), shortened links, bare IP addresses, unencrypted links, requests for passwords, codes, card details or urgent action (Hebrew and English), program files (.exe, .apk …), hidden direction characters; ClamAV for text and pictures when installed; pictures are also re-drawn in the sandbox. A suspicious message is held with the reasons, and **Show it anyway** / **Delete it**. These are warning signs, not proof, and the window says so.
- **Found and fixed on the way:**
  - updating a contact deleted their history (INSERT OR REPLACE with a cascade);
  - two big pictures crossing could block both sides;
  - a locked keyring could crash Chat instead of falling back to the file.
- **The tests (65):** 25 core tests, plus transport, pairing, pictures in the real sandbox, Tor, mDNS, the service and the command line, over real sockets. In the VM: a code, a valid user unit, Tor running as the person and gone when Chat stops, and a picture re-drawn in the sandbox without its hidden location.
- **Next:**
  - a test between two VMs: pairing and a message over the local network, then over Tor;
  - "seen" receipts when the window shows a message, and a notification that opens the conversation;
  - the privacy policy (1.1) describes Diamond Chat; like the rest of it, it needs a legal review;
  - **before release:** an external security review of the protocol and of the picture sandbox, and a trademark check of the name "Diamond Chat".

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

## 8. Decisions (made)

1. **Scope:** the internet from day one, through Tor onion services (§0), and the local network directly.
2. **Content:** text and pictures.
3. **The name:** Diamond Chat. **It requires a trademark check.**
4. **History:** kept until deleted. You can delete a conversation, or turn on deletion after N days.

---

© 2026 Diamond Rubinny (d.Ai) · D.Ai OS · Apache-2.0
