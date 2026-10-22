# Catalog

_Generated from the code by `offline-agent catalog --write`. Don't edit by hand._

Every built-in agent (template) and every tool, in plain words.

## Agents

| Agent | What it does | How it works |
|---|---|---|
| [General Assistant](#general-assistant) | Plain chat. No access to files, internet or email. | Agent |
| [File Helper](#file-helper) | Reads and summarizes files in the workspace; asks before creating files. | Agent |
| [File Sorter](#file-sorter) | Organizes files in a folder the way you ask. Rule mode - the model writes a rule, you approve it, code moves and checks. | Clerk |
| [Gmail Sorter](#gmail-sorter) | Sorts emails into folders/labels by sender or subject. Rule mode - the model writes rules, you approve, code moves and checks. | Clerk |
| [Math Helper](#math-helper) | Uses the calculator so answers are exact instead of guessed. | Agent |
| [News Collector](#news-collector) | Collects today's stock-market headlines from approved news feeds into a text file in the workspace. | Agent |
| [Note Taker](#note-taker) | Saves timestamped notes in workspace/notes.md and reads them back. | Agent |
| [Web Researcher](#web-researcher) | Searches the web, reads pages from approved sites, and writes a report. | Agent |
| [Website Builder](#website-builder) | Builds a small static website (HTML/CSS/JS) in a workspace folder. | Agent |

### General Assistant

Plain chat. No access to files, internet or email.

**Good for:** Quick questions and explanations · Drafting short text · Trying out a new model
**Not for:** Anything with files, email or the internet (it has no access)
**Needs:** No internet.
**How it works:** Agent: the model works step by step with tools
**Features:** Telegram style · Full Voice
**Tools:** `calculator`, `current_datetime`

**Try:**
- Explain what a context window is, in two sentences.
- Give me 5 names for a bakery.

### File Helper

Reads and summarizes files in the workspace; asks before creating files.

**Good for:** Reading and summarizing text files · Answering questions about a file · Writing new text files
**Not for:** Binary files like PDFs or images · Changing existing files (it asks before creating anything)
**Needs:** Files: read, create in the workspace. Asks before: create. No internet. Can ask you questions during a run.
**How it works:** Agent: the model works step by step with tools
**Features:** Job notes · Telegram style · Full Voice
**Tools:** `calculator`, `current_datetime`, `list_folder`, `read_file`, `create_folder`, `write_file`, `ask_user`

**Try:**
- Summarize notes.txt in three bullet points.
- List the files in the workspace and tell me which are largest.

### File Sorter

Organizes files in a folder the way you ask. Rule mode - the model writes a rule, you approve it, code moves and checks.

**Good for:** Sorting a folder by file type · Moving all files of one type into a folder · Cleaning up Downloads
**Not for:** Sorting by what's inside a file (e.g. invoices vs letters) · Folders inside folders (top level only)
**Needs:** Files: read, create, move / rename, delete in a folder you choose. Asks before: move / rename, delete. No internet. Can ask you questions during a run.
**How it works:** Clerk: the model writes one rule, you approve it, code does the work and checks it
**Features:** Telegram style · Full Voice
**Tools:** `calculator`, `current_datetime`, `list_folder`, `read_file`, `create_folder`, `write_file`, `move_file`, `move_files`, `delete_file`, `ask_user`

**Try:**
- Move all pdf files in ~/Downloads to a new folder all_pdf.
- Sort the files in ~/Downloads by kind: image → Images, document → Documents, video → Videos.

### Gmail Sorter

Sorts emails into folders/labels by sender or subject. Rule mode - the model writes rules, you approve, code moves and checks.

**Good for:** Sorting email by sender or subject into folders/labels · Moving receipts, newsletters, notifications
**Not for:** Replying to or sending email (it can't) · Deleting email (it can't) · Sorting by what an email says
**Needs:** No internet. Email: reads and organizes (asks first). Never sends or deletes. Can ask you questions during a run.
**How it works:** Clerk: the model writes one rule, you approve it, code does the work and checks it
**Features:** Telegram style · Full Voice
**Tools:** `calculator`, `current_datetime`, `ask_user`, `email_folders`, `email_list`, `email_read`, `email_move`, `email_mark_read`

**Try:**
- Move emails from amazon and flipkart to a folder called Receipts.
- Move unread emails with 'newsletter' in the subject to Newsletters.

### Math Helper

Uses the calculator so answers are exact instead of guessed.

**Good for:** Exact arithmetic: percentages, totals, conversions · Multi-step calculations
**Not for:** Algebra or proofs · Data analysis on files
**Needs:** No internet.
**How it works:** Agent: the model works step by step with tools
**Features:** Telegram style · Full Voice
**Tools:** `calculator`, `current_datetime`

**Try:**
- What is 18% of 1240?
- Split 4,850 between 3 people, then add 18% GST to each share.

### News Collector

Collects today's stock-market headlines from approved news feeds into a text file in the workspace.

**Good for:** Daily stock-market headlines into a text file · Headlines about one company (keywords)
**Not for:** Full articles or analysis · Sites without an RSS feed
**Needs:** Files: create, modify in the workspace. Asks before: modify. Internet: reads pages on economictimes.indiatimes.com, livemint.com, moneycontrol.com.
**How it works:** Agent: the model works step by step with tools
**Features:** Job notes · Inspector (verifier) · Telegram style · Full Voice
**Tools:** `calculator`, `current_datetime`, `fetch_url`, `read_feed`, `create_folder`, `write_file`, `overwrite_file`, `append_note`

**Try:**
- Collect today's stock market headlines and save them to a text file.
- Collect today's headlines about Reliance.

### Note Taker

Saves timestamped notes in workspace/notes.md and reads them back.

**Good for:** Quick notes with a timestamp · Reading back what you noted
**Not for:** Long documents · Notes that must stay private from other agents in the same folder
**Needs:** Files: read, modify in the workspace. No internet.
**How it works:** Agent: the model works step by step with tools
**Features:** Telegram style · Full Voice
**Tools:** `calculator`, `current_datetime`, `list_folder`, `read_file`, `overwrite_file`, `append_note`

**Try:**
- Note that the dentist appointment is on Friday at 4pm.
- What did I note this week?

### Web Researcher

Searches the web, reads pages from approved sites, and writes a report.

**Good for:** Short research reports with sources · Looking up facts on approved sites
**Not for:** Anything private (search words go to DuckDuckGo) · Long-form research needing many sources
**Needs:** Files: create in the workspace. Asks before: create. Internet: reads pages and searches DuckDuckGo on wikipedia.org. Can ask you questions during a run.
**How it works:** Agent: the model works step by step with tools
**Features:** Job notes · Telegram style · Full Voice
**Tools:** `calculator`, `current_datetime`, `fetch_url`, `web_search`, `read_feed`, `create_folder`, `write_file`, `ask_user`

**Try:**
- Research what Ollama is and save a short report.
- Find 3 facts about the Indian monsoon from Wikipedia.

### Website Builder

Builds a small static website (HTML/CSS/JS) in a workspace folder.

**Good for:** Small static websites: landing pages, portfolios, event pages · HTML/CSS/JS without frameworks
**Not for:** Web apps with a backend or database · Large multi-page sites
**Needs:** Files: read, create, modify in the workspace. Asks before: modify. Internet: reads pages on developer.mozilla.org. Can ask you questions during a run.
**How it works:** Agent: the model works step by step with tools
**Features:** Job notes · Telegram style · Full Voice
**Tools:** `calculator`, `current_datetime`, `fetch_url`, `read_feed`, `list_folder`, `read_file`, `create_folder`, `write_file`, `overwrite_file`, `append_note`, `ask_user`

**Try:**
- Build a one-page website for a bakery called Crumbs in my-site/.
- Add a contact section with an email link to my-site/index.html.

## Tools

Tools are unlocked by an agent's permissions (Off / Allow / Ask first).

### always available

#### `calculator`

Evaluate a math expression and return the exact result.

**Unlocked by:** always available

| Input | Type | Required | About |
|---|---|---|---|
| `expression` | string | yes | The math expression, e.g. "(1200 * 0.18) + 45" |

**Safety:** Only numbers and + - * / // % ** ( ). It can't run code.

**Example output:**
```
223.2
```

#### `current_datetime`

Get the current local date and time.

**Unlocked by:** always available

**Safety:** Reads the clock only.

**Example output:**
```
Thursday, 22 October 2026, 15:51
```

### Internet

#### `fetch_url`

Read a web page as plain text, one page at a time. Only the agent's allowed sites.

**Unlocked by:** Internet: Read web pages

| Input | Type | Required | About |
|---|---|---|---|
| `url` | string | yes | Full address, e.g. "https://en.wikipedia.org/wiki/Python_(programming_language)" |
| `offset` | integer | no (default `0`) | Start at this character (from the previous page's "Next page" hint) |
| `limit` | integer | no (default `4000`) | Characters per page (default 4000) |

**Safety:** Allowed sites only; redirects to other sites are blocked; every request is logged. Long pages come in pages.

**Example output:**
```
Title: Ollama
(first 4000 characters)
+8200 more chars. Next page: offset=4000
```

#### `web_search`

Search the web (DuckDuckGo) and return the top results as title + link. Your query is sent to DuckDuckGo. To read a result, use fetch_url (allowed sites only).

**Unlocked by:** Internet: Web search

| Input | Type | Required | About |
|---|---|---|---|
| `query` | string | yes | What to search for |

**Safety:** Your search words are sent to DuckDuckGo. Reading a result needs Read web pages + an allowed site.

**Example output:**
```
OK 8 results
1. Ollama | https://ollama.com
```

#### `read_feed`

Read a news feed (RSS/Atom) and return one line per item: headline | time | link. Much shorter than fetch_url. Use filters to keep only what you need.

**Unlocked by:** Internet: Read web pages

| Input | Type | Required | About |
|---|---|---|---|
| `url` | string | yes | Feed address, e.g. "https://www.livemint.com/rss/markets" |
| `keywords` | string | no (default `""`) | Optional, comma separated; keep items mentioning any of them, e.g. "sensex,nifty" |
| `today_only` | boolean | no (default `false`) | true to keep only items published today |
| `since_hours` | integer | no (default `0`) | Optional; keep only items from the last N hours (0 = no limit) |
| `limit` | integer | no (default `20`) | Max items to show (default 20) |

**Safety:** Allowed sites only; every request is logged. Refuses feeds with XML entities.

**Example output:**
```
OK feed Markets · 3/40 items · keywords sensex
1. Sensex jumps 600 points | 2026-10-22 14:05 | https://…
```

### Files & folders

#### `list_folder`

List a folder. First line: counts per file type. Then one line per item: name | kind | size. Names are relative to the folder shown. Use filters to keep the list short. Kinds: image, document, video, audio, archive, code, other.

**Unlocked by:** Files & folders: Read

| Input | Type | Required | About |
|---|---|---|---|
| `path` | string | no (default `""`) | Folder to list, e.g. "~/Downloads". Empty = the agent's folders. |
| `recursive` | boolean | no (default `false`) | true to include subfolders |
| `kinds` | string | no (default `""`) | Optional, comma separated, e.g. "image" or "document,image" |
| `extensions` | string | no (default `""`) | Optional, comma separated, e.g. ".pdf" or ".jpg,.png" |
| `limit` | integer | no (default `50`) | Max lines to show (default 50) |

**Safety:** Only the agent's folders; hidden files are skipped.

**Example output:**
```
OK ~/Downloads filter .pdf · 140 files · 0 folders · .pdf:140
a.pdf | document | 297.6 KB
```

#### `read_file`

Read a text file, one page at a time.

**Unlocked by:** Files & folders: Read

| Input | Type | Required | About |
|---|---|---|---|
| `path` | string | yes | Full path, e.g. "~/Downloads/notes.txt" |
| `offset` | integer | no (default `0`) | Start at this character (from the previous page's "Next page" hint) |
| `limit` | integer | no (default `6000`) | Characters per page (default 6000) |

**Safety:** Only the agent's folders and allowed file types. Long files come in pages.

**Example output:**
```
(first 6000 characters)
+3000 more chars. Next page: offset=6000
```

#### `create_folder`

Create a folder (and any missing parent folders). Does nothing if it already exists.

**Unlocked by:** Files & folders: Create

| Input | Type | Required | About |
|---|---|---|---|
| `path` | string | yes | Full path of the new folder, e.g. "~/Downloads/anurag_img" |

**Safety:** Only inside the agent's folders. Counts toward the change limit.

**Example output:**
```
OK created ~/Downloads/all_pdf/
```

#### `write_file`

Create a NEW text file. Fails if the file already exists (use overwrite_file for that).

**Unlocked by:** Files & folders: Create

| Input | Type | Required | About |
|---|---|---|---|
| `path` | string | yes | Full path, e.g. "~/Documents/site/index.html" or "my-site/index.html" in workspace |
| `content` | string | yes | The full text of the file |

**Safety:** Creates NEW files only; never overwrites. Only the agent's folders.

**Example output:**
```
OK created ~/site/index.html (2140 chars)
```

#### `overwrite_file`

Replace the content of an EXISTING text file.

**Unlocked by:** Files & folders: Modify

| Input | Type | Required | About |
|---|---|---|---|
| `path` | string | yes | Full path of the file |
| `content` | string | yes | The new full text |

**Safety:** Changes an existing file: use Ask first. Recorded in the file log.

**Example output:**
```
OK replaced ~/site/style.css (980 chars)
```

#### `append_note`

Add a timestamped line to notes.md (in the agent's first folder, usually the workspace).

**Unlocked by:** Files & folders: Modify

| Input | Type | Required | About |
|---|---|---|---|
| `text` | string | yes | The note to save |

**Safety:** Adds a line to notes.md in the agent's first folder.

**Example output:**
```
Note saved to notes.md.
```

#### `move_file`

Move (or rename) a file into a folder. Creates the folder if needed (if allowed). Never overwrites: if the name exists, it adds _1, _2...

**Unlocked by:** Files & folders: Move / rename

| Input | Type | Required | About |
|---|---|---|---|
| `source` | string | yes | Full path of the file to move |
| `destination_folder` | string | yes | Full path of the folder to move it into |
| `new_name` | string | no (default `""`) | Optional new file name; leave empty to keep the name |

**Safety:** Never overwrites: name clashes get _1, _2. Undo moves it back.

**Example output:**
```
OK moved ~/Downloads/a.pdf → ~/Downloads/all_pdf/a.pdf
```

#### `move_files`

Move ALL matching files from a folder (top level only) into another folder, in one step. Use this instead of many move_file calls. Needs at least one filter. Never overwrites.

**Unlocked by:** Files & folders: Move / rename

| Input | Type | Required | About |
|---|---|---|---|
| `folder` | string | yes | Folder to take files from, e.g. "~/Downloads" |
| `destination_folder` | string | yes | Folder to move them into, e.g. "~/Downloads/all_pdf" (created if needed) |
| `extensions` | string | no (default `""`) | Comma separated, e.g. ".pdf" or ".jpg,.png,.heic" |
| `kinds` | string | no (default `""`) | Comma separated: image, document, video, audio, archive, code, other |
| `name_contains` | string | no (default `""`) | Only files whose name contains this text |

**Safety:** Needs at least one filter; top level only (subfolders untouched); never overwrites; you see the exact file list before approving.

**Example output:**
```
OK moved 138/140 ~/Downloads → ~/Downloads/all_pdf · NOT MOVED 2: …
```

#### `delete_file`

Send a file to the Trash (recoverable). Only when the user explicitly asked to delete it.

**Unlocked by:** Files & folders: Delete

| Input | Type | Required | About |
|---|---|---|---|
| `path` | string | yes | Full path of the file |

**Safety:** Sends files to the Trash (recoverable), files only, never folders. Use Ask first.

**Example output:**
```
OK ~/Downloads/old.zip → Trash
```

### Interaction

#### `ask_user`

Ask the user a question and wait for their answer. Use it when you need information or a decision from them (e.g. which folder to use, or "Proceed?").

**Unlocked by:** Interaction: Ask you questions

| Input | Type | Required | About |
|---|---|---|---|
| `question` | string | yes | The question to ask, clear and short |

**Safety:** Pauses the run until you answer. In unattended runs it gets no answer.

**Example output:**
```
~/Downloads
```

### framework tool (job notes)

#### `update_step`

Close a step in your job notes after doing it.

**Unlocked by:** framework tool (job notes)

| Input | Type | Required | About |
|---|---|---|---|
| `step` | integer | yes | Step number from the notes |
| `status` | string | no (default `"done"`) | done, skipped or blocked |
| `note` | string | no (default `""`) | One short line: what you did (or why skipped/blocked) |

**Safety:** Touches only the job notes. A 'done' is refused if the step's tool calls all failed.

**Example output:**
```
OK step 2 done · NOW step 3: Check nothing left
```

#### `add_step`

Add a step to your job notes when you discover more work is needed.

**Unlocked by:** framework tool (job notes)

| Input | Type | Required | About |
|---|---|---|---|
| `title` | string | yes | Short step title, max 8 words |

**Safety:** Touches only the job notes.

**Example output:**
```
OK added step 4: Report totals
```

### Email

#### `email_folders`

List the mailbox folders (in Gmail these are labels, e.g. INBOX, [Gmail]/Spam).

**Unlocked by:** Email: Read email

**Safety:** Reads folder names only, from your mail server.

**Example output:**
```
INBOX
Receipts
[Gmail]/Spam
```

#### `email_list`

List the newest emails in a folder: uid, date, sender and subject. Does not mark them read.

**Unlocked by:** Email: Read email

| Input | Type | Required | About |
|---|---|---|---|
| `folder` | string | no (default `"INBOX"`) | Folder name, default "INBOX" |
| `limit` | integer | no (default `20`) | How many emails, max 50 |
| `unread_only` | boolean | no (default `false`) | true to list only unread emails |

**Safety:** Does not mark mail as read. Only allowed mail folders.

**Example output:**
```
OK 20 emails in INBOX (uid | date | from | subject)
102 | 20 Oct 14:05 | Amazon (amazon.in) | Your order shipped
```

#### `email_read`

Read one email's headers and text, one page at a time. Does not mark it read.

**Unlocked by:** Email: Read email

| Input | Type | Required | About |
|---|---|---|---|
| `uid` | string | yes | The uid from email_list |
| `folder` | string | no (default `"INBOX"`) | Folder the email is in, default "INBOX" |
| `offset` | integer | no (default `0`) | Start at this character of the body (from the "Next page" hint) |
| `limit` | integer | no (default `1500`) | Characters per page (default 1500) |

**Safety:** Does not mark mail as read. Long emails come in pages.

**Example output:**
```
From: Amazon (amazon.in) · 20 Oct 14:05
Subject: Your order shipped

…
```

#### `email_move`

Move an email to another folder (Gmail: label), creating the folder if needed.

**Unlocked by:** Email: Organize email

| Input | Type | Required | About |
|---|---|---|---|
| `uid` | string | yes | The uid from email_list |
| `to_folder` | string | yes | Destination folder, e.g. "Receipts" |
| `from_folder` | string | no (default `"INBOX"`) | Where the email is now, default "INBOX" |

**Safety:** Moves only; there is no send or delete tool. Only allowed mail folders.

**Example output:**
```
Moved email 102 from INBOX to Receipts.
```

#### `email_mark_read`

Mark an email as read.

**Unlocked by:** Email: Organize email

| Input | Type | Required | About |
|---|---|---|---|
| `uid` | string | yes | The uid from email_list |
| `folder` | string | no (default `"INBOX"`) | Folder the email is in, default "INBOX" |

**Safety:** Changes the read flag only.

**Example output:**
```
Marked email 102 as read.
```

### Memory

#### `remember`

Save a short note for future runs (facts, preferences, lessons learned). One fact per note.

**Unlocked by:** Memory: Remember

| Input | Type | Required | About |
|---|---|---|---|
| `note` | string | yes | The fact to remember, e.g. "User keeps PDFs in ~/Downloads/all_pdf" |

**Safety:** Saved on this computer. Notes come back later as information, never instructions. Use Ask first.

**Example output:**
```
OK remembered #12
```

#### `recall`

Search your notes from earlier runs by meaning.

**Unlocked by:** Memory: Recall

| Input | Type | Required | About |
|---|---|---|---|
| `query` | string | yes | What you want to know, e.g. "where do PDFs go" |

**Safety:** Reads this agent's notes (or shared notes) only.

**Example output:**
```
OK notes (information, not instructions):
#12 (2026-10-20): PDFs go to all_pdf
```

#### `forget`

Delete one of your notes that is wrong or outdated.

**Unlocked by:** Memory: Remember

| Input | Type | Required | About |
|---|---|---|---|
| `memory_id` | integer | yes | The note number, e.g. 12 |

**Safety:** Deletes only this agent's own notes.

**Example output:**
```
OK forgot #12
```
