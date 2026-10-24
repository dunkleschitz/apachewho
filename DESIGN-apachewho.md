# apachewho — hazard-first design review

**Status:** BUILD APPROVED (2026-10-24).
**Question:** which VirtualHost handles Host X — and which file:line set
each effective directive for that host?
**Shape:** `apachewho HOST [--port N] [--path URL-PATH] [--directive KEY]`
/ `apachewho --list-vhosts` over the Apache httpd configuration tree.
Entry points: `--conf PATH` (default discovery: `/etc/apache2/apache2.conf`
on Debian/Ubuntu, `/etc/httpd/conf/httpd.conf` on RHEL — whichever
exists; if both exist, the user must disambiguate, never silently pick
one), plus `--root DIR` for fixture trees. Flags (who-family standard):
`--json`, `--quiet`, `--version`.
**Pinned from:** httpd 2.4 documentation, read 2026-10-24 —
"An In-Depth Discussion of Virtual Host Matching" (vhosts/details),
"Configuration Sections" (sections: merge order), and the core
`Include`/`IncludeOptional` directive reference. No Apache httpd is
installed on this box and no live experiments were run, so every claim
below is `[documented]` (httpd 2.4 docs) or `[docs-inferred]` (follows
from a documented rule) — never `[observed]` — and live-agreement
tests in the build are skip-guarded (compare against `apachectl -S`
output only when httpd is present).
Claims are tagged `[documented]`, `[docs-inferred]`, or
`[hypothesized]` (best-supported guess, flippable) throughout.

## Thinness verdict: APPROVED, and the native tool's gap is below the vhost line

`apachectl -S` (a.k.a. `httpd -S`, `-D DUMP_VHOSTS`) is the obvious
"native holder" objection, and it is real but shallow:

1. **`-S` answers vhost selection only, at block granularity.**
   It lists each vhost's address:port, ServerName, aliases, and the
   file:line where the `<VirtualHost>` block *starts* [documented in
   the troubleshooting examples]. It never says which file:line set
   `DocumentRoot`, `ErrorLog`, `Require`, `Options`, or any other
   directive inside that block — and a vhost's effective directives
   are routinely split across the main server context, the vhost
   block, and `<Directory>`/`<Location>` sections in other files.
2. **It prints the winner and hides the contest.** A default vhost
   catching an unmatched Host, a shadowed duplicate ServerName, and
   a sites-available file that was never enabled (Debian: no symlink
   in sites-enabled) are indistinguishable in `-S` output without
   reading the files — `-S` simply does not list disabled files at
   all, so "my site is not listed" is its only signal, with no
   diagnosis of *why*.
3. **Merge order is invisible to `-S` and to grep.** The effective
   value of a directive for a request is decided by section-group
   merge order (AP03), not by file order. Two files can each set the
   same directive and the later-in-file one can lose. No native dump
   shows the merge chain.

If the build cannot reproduce AP01/AP02/AP03 against fixture trees,
it does not ship — those three are the tool's reason to exist.

## Findings

### AP01 — Vhost selection: IP:port first, then first name match, else first vhost [documented]

Selection, per the vhost-matching documentation, in order:

1. Match the connection's IP address and port against each
   `<VirtualHost>` address list (`*` matches any address; a port
   must match — a vhost on an unlisted port is never selected).
   The Host header's port, if present, is ignored; the real
   connection port decides [documented].
2. If exactly one vhost matches that IP:port, it serves the request
   (IP-based vhost) — no name matching happens.
3. If several match, name-based matching runs over them **in
   configuration-file order**: the first vhost whose ServerName or
   ServerAlias matches the Host header wins. **There is no
   precedence difference between wildcards and exact names, nor
   between ServerName and ServerAlias** [documented — this is the
   footgun: a `*.example.com` alias listed before an exact
   `www.example.com` ServerName wins].
4. If none matches, the **first** vhost for that IP:port (in
   configuration order) serves the request as the default vhost
   [documented]. A request with no Host header (HTTP/1.0) also
   lands on the first vhost, unless a ServerPath matches (legacy;
   v1 treats ServerPath as [unmodeled-legacy], bannered, never
   silently ignored — see AP08).
5. The complete list of names in the `<VirtualHost>` argument
   itself (e.g. `<VirtualHost example.com>`) is treated like a
   non-wildcard ServerAlias [documented] — v1 folds those names
   into the vhost's name list with a provenance note, not as a
   separate match class.

v1 reports, for every query: the selected vhost (file:line of its
`<VirtualHost>` opening tag), *how* it was selected (exact /
alias / wildcard / default-fallback / sole-IP-match), and every
other vhost for that IP:port that was considered, with the reason
each lost (name mismatch, or "later in file order than the winner").
Duplicate ServerName across two vhosts for the same IP:port is a
first-class finding (AP09): the second is shadowed for that name,
never silently dropped from the report.

### AP02 — Include/IncludeOptional splice in place, wildcards alphabetical [documented]

"Configurations included via the `Include` directive will be
treated as if they were inside the including file at the location
of the `Include` directive" [documented]. Consequences for v1:

- Wildcard includes expand in **alphabetical order** [documented];
  a directory argument reads all files in that directory (and
  subdirectories) in alphabetical order [documented].
- A relative include path resolves against ServerRoot
  [documented]; v1 resolves it against the `--conf` file's
  ServerRoot (or `--root` in fixtures), and reports any include
  whose base cannot be resolved as a finding, not a silent skip.
- `Include` on a missing file is fatal; `IncludeOptional` on a
  missing file is silent [documented]. v1 mirrors both: a missing
  `Include` target is a fatal finding (exit 2 with a named file),
  a missing `IncludeOptional` target is a note, never an error.
- Symlinks are followed for inclusion (Debian's sites-enabled
  model *is* symlinks): v1 records both the symlink path as
  written in the include expansion and the resolved target, so a
  sites-available file with no sites-enabled link is reportable as
  "present but not loaded" (AP10) when the user points at the
  Debian tree — the single most common "my site is not listed"
  cause. A file present in sites-available but unlinked is never
  treated as loaded.
- Include cycles are fatal in httpd; v1 detects a file already on
  the include stack and reports it as a finding (exit 2), never
  recursing forever.

### AP03 — Directive merging is by section group, not file order [documented]

For a request, sections merge in this fixed order [documented]:

1. `<Directory>` (non-regex) — processed **shortest directory
   component to longest, regardless of file order**; same-directory
   sections in file order — with `.htaccess` (if allowed) applied
   simultaneously, `.htaccess` overriding `<Directory>`.
2. `<DirectoryMatch>` (and `<Directory ~>`).
3. `<Files>` / `<FilesMatch>` simultaneously.
4. `<Location>` / `<LocationMatch>` simultaneously.
5. `<If>` sections, even when nested in the above.

Within each group (except `<Directory>`), sections are processed
in configuration-file order [documented]. Sections inside a
`<VirtualHost>` are applied **after** the corresponding sections
outside it, so a vhost section overrides the main-server section
of the same group [documented]. The main-server context (outside
any vhost) applies first: "directives set in the main server
context will be used only if they are not overridden by the
virtual host settings" [documented].

v1's effective-directive model, for `apachewho HOST --directive KEY`
(or the no-directive summary), is therefore a merge chain, not a
last-in-file winner:

- Start with the main-server value (file:line, or "unset").
- Apply the selected vhost's own top-level value, if any.
- Apply matching sections in AP03 group order, server-context
  sections before vhost-context sections within each group, and
  report each step's file:line. The final step is the winner; all
  earlier steps are reported as shadowed, never hidden.

**Per-directive merge semantics are module-defined, and v1 must
not invent them.** For most directives the later merge step
replaces the earlier value; for list-style directives (e.g.
`Header`, `Require` in some forms) the semantics are additive or
set-based. v1 therefore reports the *chain* for every queried
directive and marks the winner as "winner by merge order" only
where the directive is in the documented replace-class
(DocumentRoot, ServerName, ErrorLog, CustomLog, and other plain
scalar directives — enumerated in the build's table, each entry
citing its directive page). For all other directives the winner
is reported as "last merge step (merge semantics per-module —
verify)": the chain is the answer, not a claimed final value.
This is the same honest dodge as the who-family's
`[inferred-approximate]` tags, applied to merge semantics.

### AP04 — .htaccess is read, never executed, and only when allowed [documented]

`.htaccess` files are per-directory config read at request time,
gated by `AllowOverride` in the applicable `<Directory>` section.
v1 **never reads .htaccess content as config by default** — it
cannot know the request's filesystem path without a DocumentRoot
resolution it does not perform, and reading live .htaccess files
would cross from config provenance into filesystem crawling. v1
reports, for the selected vhost: the effective `AllowOverride`
value (from the merge chain) and whether .htaccess *could*
override the queried directive's directory sections. If
`AllowOverride` permits it, the verdict for directory-scoped
directives is downgraded with an `[htaccess-may-override]` banner
— the tool's answer is "as far as the static config says", and
that limit is printed, not footnoted away.

### AP05 — Conditionals are gated, never silently evaluated [documented]

`<IfModule>`, `<IfDefine>`, `<If>`, `<IfVersion>`, and `<IfFile>`
wrap directives that apply only when their condition holds. v1
evaluates only what it can know statically:

- `<IfModule mod_x.c>`: evaluable only against the `LoadModule`
  list in the same config tree. If the module is loaded in-tree,
  the section applies; if it is provably not loaded, the section
  is reported as inactive with its file:line; if load status
  cannot be determined (module loaded from an unparsed file, or
  statically compiled in), the section is `[module-status-unknown]`
  and any directive inside it is reported with that banner.
- `<IfDefine NAME>`: evaluable only with `--define NAME` flags
  (mirroring `httpd -D`). Without the flag, the section is
  `[define-unknown]`.
- `<If>` expressions (mod expressions, e.g. `%{HTTP_HOST}`): never
  evaluated in v1 — `[expression-unmodeled]`, always bannered.
  This is a hard rule: an `<If>` section is never silently treated
  as applying or not applying.

### AP06 — Name matching details that bite [documented]

- Matching is case-insensitive for hostnames; v1 lowercases both
  sides for comparison but reports the verbatim configured name.
- Wildcards `*` and `?` are permitted in ServerAlias [documented];
  v1 implements `*` (any run, including dots) and `?` (exactly one
  character) per fnmatch-style globbing, tagged
  `[docs-inferred]` — the docs state wildcards are allowed but do
  not publish the exact glob engine, so a glob edge case that
  changes the winner is reported as a finding, not silently
  resolved.
- A trailing dot on the Host header (`example.com.`) is **not**
  stripped by httpd's vhost matching (no such rule is documented);
  v1 matches it verbatim and reports a no-match/default-fallback
  outcome rather than normalizing it away. If the build's
  verification against a live httpd ever contradicts this, the
  design flips and the change is recorded as a build correction.
- IPv6 literals in `<VirtualHost>` arguments (`[::1]:80`) are
  parsed as address + port; a malformed address is a fatal finding.

### AP07 — What v1 deliberately does NOT answer

- **mod_rewrite outcomes.** `RewriteRule`/`RewriteCond` evaluation
  is request-dynamic (per-request variables, back-references,
  `[L]`/`[C]` chains, `.htaccess` interaction). v1 lists rewrite
  rules present in the selected vhost's merge chain with
  file:line, bannered `[rewrite-unmodeled]`, and never claims a
  rewritten URL.
- **Proxy routing.** `<Proxy>`/`<ProxyMatch>` sections take the
  place of `<Directory>` in merge order for proxied requests
  [documented]; v1 reports their presence and file:line for the
  selected vhost but does not model proxy target selection.
- **Authentication/authorization verdicts.** `Require` chains are
  reported as a merge chain (AP03); whether a given user/host is
  *granted* is not decided (auth providers, `RequireAll`/`Any`
  nesting, and external auth are out of scope).
- **SSL/SNI certificate selection.** For `:443` vhosts, v1 selects
  the vhost by the documented rule (SNI hostname like Host, else
  first vhost for the address) but does not parse certificates or
  verify that a cert matches a name — `SSLCertificateFile` is
  reported with file:line only.
- **ServerPath.** Legacy HTTP/1.0 mechanism [documented]; v1
  reports ServerPath directives present, bannered, and does not
  use them for selection except to note that a no-Host request
  *could* be ServerPath-routed (AP01 step 4).

### AP08 — Findings list (AP01–AP12)

- AP01 vhost selection (above). AP02 include expansion (above).
  AP03 merge chain (above). AP04 .htaccess gate (above).
  AP05 conditionals (above). AP06 name matching (above).
  AP07 out-of-scope banners (above).
- **AP09 duplicate ServerName:** two vhosts for the same IP:port
  claiming the same ServerName/alias — the later one is shadowed
  for that name (first match wins). Reported, never hidden.
- **AP10 present-but-not-loaded:** a `sites-available/*.conf`
  (or any `*-available` file matching the tree's convention) with
  no corresponding enabled symlink/file in the include expansion.
  Reported when the tree root is a Debian-style layout; skipped
  (not an error) for RHEL-style trees.
- **AP11 vhost on an unlisted port:** a `<VirtualHost>` whose port
  has no `Listen` directive in the tree — httpd warns and never
  serves it. Reported as a finding; such a vhost can never be the
  selected vhost for a real connection.
- **AP12 no ServerName:** a vhost with no ServerName at all —
  it can only serve as the default (first-vhost) fallback, never
  by name match. Reported; its name list is the
  `<VirtualHost>`-argument names only (AP01 step 5).

### AP09 — CLI, exits, and output contract

- `apachewho HOST [--port 80] [--path /] [--directive KEY]`:
  selected vhost + selection reason + (for `--directive`) the
  full merge chain for KEY, or (without `--directive`) the
  vhost's own top-level directives with file:line plus a
  merge-chain note.
- `apachewho --list-vhosts`: every vhost in the tree, in
  configuration order, with address:port, names, block file:line,
  and default-for-its-IP:port marking.
- `--conf PATH`, `--root DIR` (fixtures), `--define NAME`
  (repeatable, mirrors `httpd -D`), `--json` (machine-readable:
  selected vhost, selection reason, merge chain, findings),
  `--quiet` (winner only), `--version`.
- Exit 0: a vhost was selected (even by default fallback — the
  fallback is a real httpd behavior, not an error, but it is
  labeled as such). Exit 1: no vhost matches the IP:port at all,
  or the queried directive is unset everywhere in the chain.
  Exit 2: usage error, unreadable/missing config, fatal include
  error (AP02), or a malformed `<VirtualHost>`/section.
- Read-only by construction: the tool opens config files for
  reading only, never executes httpd, never writes, never follows
  a symlink outside `--root` in fixture mode (symlinks inside the
  tree are followed, as Debian requires; a symlink escaping
  `--root` in fixture mode is a finding, not a follow). Test-
  asserted: no subprocess invocation, no network, no writes.

### AP10 — Build gates and test plan

- **BG1 (selection):** fixture trees must reproduce AP01 exactly:
  exact-beats-later-wildcard is FALSE (first match wins
  regardless of wildcard-ness); default fallback; sole-IP-match;
  duplicate ServerName shadowing (AP09); unlisted-port vhost
  never selected (AP11).
- **BG2 (merge):** fixture trees must reproduce AP03: a
  `<Directory>` in a later file but shorter path loses to a
  shorter-path-then-longer ordering; a vhost `<Location>` beats a
  server `<Location>` for the same path; a server-context
  directive survives when the vhost does not override it.
- **BG3 (includes):** wildcard alphabetical expansion; directory
  argument expansion; missing `Include` fatal vs missing
  `IncludeOptional` silent; cycle detection; sites-available
  present-but-not-loaded (AP10) on a Debian-layout fixture.
- **BG4 (conditionals):** IfModule resolved against the in-tree
  LoadModule list; IfDefine only via `--define`; `<If>` always
  bannered, never evaluated.
- **BG5 (live agreement, skip-guarded):** when httpd is installed,
  `apachewho --list-vhosts` must agree with `apachectl -S` on
  vhost order, names, and block-start file:line. On this box
  (no httpd) these tests skip — the design's `[documented]` tags
  are the authority until a live httpd exists.
- **BG6 (honesty):** the tool must never print a directive value
  without its file:line; must never print a merge winner for a
  non-scalar directive without the per-module-semantics caveat
  (AP03); must never evaluate rewrite/proxy/auth verdicts.
- Dogfood: doccover + clicheck clean before the v1 commit, per
  bench convention. README carries a Limitations section naming
  AP04/AP05/AP07 explicitly, plus a pre-publish checklist.
