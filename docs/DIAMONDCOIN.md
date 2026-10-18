# DiamondCoin: a plan for approval (not built)

> Status: **plan only.** No code until the plan is approved. The legal sections are a technical draft and **require legal review**. The name **requires a trademark check**.

## 1. What I understood

- **The request:** when Diamond (the local AI) and system processes are used, the user earns virtual "coins" called **DiamondCoin**.
- **Moving coins:** coins can be moved between computers (between operating systems).
- **Open question:** what the coins are good for, and whether they are worth money. Most of the decisions depend on that answer (§3).

## 2. Three facts that change everything

1. **D.Ai is open source (Apache-2.0).** Anything counted on the user's computer can be forged by anyone: changing one line of code prints coins. So:
   - Coins with **real value** can't be "minted" on the computer. They need a server, or a blockchain, that verifies every earning.
   - Coins **with no monetary value** (points) can be counted locally, because nobody gains from forging them.
2. **"Money from processes" = mining.**
   - Mining burns CPU and battery for nothing useful. That contradicts D.Ai's promise: fast, battery-friendly, private.
   - It looks exactly like cryptojacking. Antivirus tools would flag D.Ai, and so would reviews.
   - **My recommendation: never mine.** Earn from useful actions instead (§4).
3. **Value has to come from somewhere.** If a coin can be exchanged for money or goods, someone has to pay for it. Otherwise it is either worth nothing, or a promise the project can't keep.
   - **Regulation:** a coin with monetary value, transferable or tradeable, is very likely a regulated financial asset:
     - **Israel:** the Supervision of Financial Services Law (financial asset services), the anti-money-laundering order, and the Israel Securities Authority if it looks like an investment.
     - **EU:** MiCA (a white paper for a token, a CASP licence for whoever runs transfers), AML/KYC.
   - All of this **requires legal review**, and it is far beyond an OS project.

## 3. Options

| | A. Points with no monetary value (recommended for an MVP) | B. A real token on an existing blockchain | C. A blockchain of our own |
|---|---|---|---|
| What it is | "Diamonds" that unlock things in D.Ai, not convertible to money and not for sale | ERC-20 or similar, with exchange value | A new network |
| Earning | Useful actions, counted locally (forgeable, but pointless to forge) | Only by a server that verifies; wallet keys | Consensus, nodes |
| Moving between computers | A signed voucher (QR or file), redeemed once | On the chain | On the chain |
| Regulation | Low (still: terms of use, and the statement "has no monetary value") | **High:** MiCA, financial services licence, AML/KYC | **Very high**, plus large engineering |
| Cost, risk | Small, a few weeks | Large, legal and ongoing operations | Very large |

## 4. What earns coins: useful actions, not burning CPU (proposal)

- **D.Ai improves:**
  - A Raz report you chose to send (scrubbed).
  - A translation fix for one of the eight languages.
  - A Forge recipe or app shared with others and approved.
- **The computer gets safer:** fixing a security score with Tune, setting up encrypted backups, an update that went smoothly.
- **Learning Diamond:**
  - The first time with each feature, such as voice, Find, or a reply draft in J. Once, not per use.
  - So it doesn't push people to "ask the AI a lot".
- **What doesn't count:** AI usage time, the number of questions, CPU, anything another app could inflate.

**Privacy:** only "action X happened, at time Y" is counted. Not what was asked, not what was written, not files. Everything stays local unless the user moves coins (§5).

## 5. Moving coins between computers (option A)

- **Keys:** each installation has an Ed25519 key, in the keyring, never written to disk in plain text.
- **A voucher:** "N coins, from key K1 to key K2, number n, signed by K1". It moves as a file, a QR code, or through J.
- **Spending twice:** points with no value tolerate this risk. Alternatively, an optional central ledger later: it stores only voucher numbers, not identities.
- **Other operating systems:** a small open-source wallet (a web page or Python) that reads vouchers. Windows and macOS are possible later.

## 6. Threat model (short)

| Asset | Threat | Control |
|-------|--------|---------|
| The balance | Forging (open source) | Option A: no value, so no motive. Option B: only a server verifies |
| The key | Theft, a copied voucher | Keyring; a voucher bound to the receiving key; a voucher number |
| Privacy | Profiling of AI usage | Counting only the type of action; no content; local only |
| Battery and trust | "Mining in the background" | No mining at all; Raz checks that nothing burns CPU |
| Fraud | "Buy DiamondCoin" scams in the project's name | Option A: no sale; a clear statement in the terms |

## 7. Name

- "DiamondCoin" or "Diamond Coin" **may already be in use.** Cryptocurrencies named "Diamond" (DMD) and others have existed for years.
- **Requires a trademark check** before the name appears in the product.
- Alternatives that fit D.Ai's language: "Diamonds" (יהלומים), "Sparks" (ניצוצות), "D.Ai Points".

## 8. If option A is approved: the work plan

1. **`dai-coin` core:** a local ledger (SQLite, 0600), a closed list of earning events, daily limits, and signed vouchers. Tests.
2. **Display:** the balance in D.Ai Quick, a 💎 on the Living Diamond when you earn, and history in MOM or a small window. Accessible, in RTL.
3. **Earning:** hooks in Raz, Tune, Backup, Forge and Welcome (the closed list in §4).
4. **Moving:** `dai-coin send/receive`, plus QR. A VM test between two VMs, or a voucher file.
5. **Documents:** a terms-of-use clause ("no monetary value, not transferable for consideration"), privacy, and a draft for **legal review**.

---

© 2026 Diamond Rubinny (d.Ai) · D.Ai OS · Apache-2.0
