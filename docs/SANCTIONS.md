# Sanctions-list screening

Yahmi screens the **supplier name** on an invoice against two public lists and shows the result as one more finding, citing the list and its date.
It is a screening aid: a name match is a reason to check who the supplier is, never proof. It does not replace a business's own compliance duties.

## Sources (public, official)
- **UN Security Council Consolidated List** (XML), https://scsanctions.un.org/resources/xml/en/consolidated.xml, linked from https://main.un.org/securitycouncil/content/un-sc-consolidated-list . Questions about the list: sc-sanctionslists@un.org. Used here: 1,010 entries (736 individuals, 274 entities) on 21 Oct 2026.
- **UAE Local Terrorist List** (Excel), published by the Executive Office for Control and Non-Proliferation (EOCN), https://www.uaeiec.gov.ae/en-us/un-page . Used here: 311 entries (171 individuals, 140 entities and organisations) on 21 Oct 2026. Names on the sheets for delisted parties are skipped.
- Terms of use: both are published by the issuing bodies for implementing the measures. Check each site's terms before redistributing the files; this repo does not contain them (`data/sanctions/` is git-ignored).

## How it works
- `tools/update_sanctions.py` downloads both files and writes `data/sanctions/entries.json` (names, aliases, list, reference number, the fetch date and a SHA-256 of each file). The EOCN site rejects some scripted clients, so the script uses `curl`; if a download fails, save the file from the source page into `data/sanctions/raw/` and run the script again. The EOCN file id changes when the list is republished.
- `yahmi/sanctions.py` normalises names (case, punctuation, Arabic letter variants, legal suffixes like LLC) and matches:
  - **exact entity name or alias: red** ("verify with the supplier", with the list, reference and the matched name);
  - **very similar entity name** (token-sort similarity 92 or more, at least two shared words): amber;
  - **individuals:** exact full name with three or more words only, amber, never red (two-word personal names collide constantly);
  - single short words are never matched. No match gives a green line with the list dates.
- The thresholds are fixed in advance and were not tuned on any data. If `entries.json` is missing the check is silent, and if the lists are over 7 days old it adds an info line asking for a refresh.

## Measured so far (21 Oct 2026, synthetic checks only)
- 407 of 414 list entities are found when their own name is screened (the other 7 are single short words, skipped on purpose).
- 0 matches on 1,408 invented UAE-style company names (22 name stems x 16 activities x 4 legal suffixes).
- Not measured: false alarms on real supplier names. Do that on the pilot invoices (`eval/pilot_report.py` reports warnings per check).

## Limits
- Name matching only: no addresses, dates of birth, IDs or beneficial owners. Transliteration differences between Arabic and Latin spellings can be missed.
- The EOCN expects reporting entities to screen within 24 hours of a list update. Yahmi is not one of them and does not do continuous screening. Refresh before relying on it.
- The lists change: the EOCN publishes changes as Cabinet resolutions and has an alert email system.
