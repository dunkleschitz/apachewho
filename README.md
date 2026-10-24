# apachewho

Which VirtualHost handles Host X — and which file:line set each
effective directive for that host?

`apachectl -S` lists vhosts at block granularity only: it never says
which file:line set `DocumentRoot`, `ErrorLog`, `Require`, or any
other directive inside the block, and it hides the contest (a default
vhost catching an unmatched Host, a shadowed duplicate ServerName, a
sites-available file that was never enabled). `apachewho` is a static
model of httpd 2.4's documented vhost-selection and section-merge
rules that answers both questions with file:line provenance.

## Usage

```
apachewho HOST [--port N] [--bind IP] [--path URL-PATH]
               [--directive KEY] [--conf PATH] [--root DIR]
               [--define NAME] [--json] [--quiet] [--version]
apachewho --list-vhosts [--conf PATH] [--root DIR] [--json] [--quiet]
```

- `HOST` is the Host header value to query. A port on the Host header
  is ignored — the connection port (`--port`, default 80) decides,
  exactly as httpd ignores the Host header's port.
- `--directive KEY` resolves one directive through the AP03 merge
  chain (main server, then the selected vhost, then matching sections
  in group order) and reports every step with file:line.
- `--list-vhosts` lists every vhost in configuration order, with
  address:port, names, block file:line, and default-for-port marking.
- `--conf PATH` is the entry config file (default discovery:
  `/etc/apache2/apache2.conf`, then `/etc/httpd/conf/httpd.conf`).
  `--root DIR` is a fixture tree root: it sets ServerRoot for relative
  includes and is the base for the sites-available check; symlinks
  escaping it are reported, not followed.
- `--define NAME` (repeatable) mirrors `httpd -D` for `<IfDefine>`.
- Exit codes: 0 = a vhost was selected (default fallback included,
  labeled as such); 1 = no vhost for the port, or the queried
  directive is unset everywhere; 2 = usage error, unreadable/missing
  config, fatal include error, or a malformed `<VirtualHost>`/section.

## Example

```
$ apachewho www.example.com --conf /etc/apache2/apache2.conf
host www.example.com port 80 -> /etc/apache2/sites-enabled/a.conf:1 (*:80)
  selection: exact ServerName match on 'www.example.com'
  ...

$ apachewho www.example.com --directive DocumentRoot --path /app/x
  directive DocumentRoot merge chain (AP03 order):
    /etc/apache2/apache2.conf:4 [main] = /var/www/default (shadowed)
    /etc/apache2/sites-enabled/a.conf:4 [vhost] = /var/www/a (winner by merge order)
```

## Findings

| Code | Meaning |
|------|---------|
| AP02 | Include problem: missing `Include` (fatal), missing `IncludeOptional` (note), include cycle (fatal), include escaping the fixture root (not followed) |
| AP05 | Conditional section inactive (module not in the in-tree `LoadModule` list) or gated (`[module-status-unknown]`, `[define-unknown]`, `[expression-unmodeled]`) |
| AP09 | Duplicate ServerName/alias for the same port: the later vhost is shadowed (first match wins) |
| AP10 | Present but not loaded: a `sites-available/*.conf` file with no enabled counterpart in the include expansion |
| AP11 | Vhost on an unlisted port: no `Listen` for it in-tree, so httpd warns and never serves it (fires only when the tree declares at least one `Listen`) |
| AP12 | Vhost with no ServerName: can only serve as the default fallback, never by name match |

## Limitations

- Static model, not a live httpd verdict. Every rule is
  `[documented]` (httpd 2.4 docs) or `[docs-inferred]`; no httpd is
  installed on the build box, so live-agreement tests against
  `apachectl -S` are skip-guarded (BG5).
- Vhost selection is by port (plus `--bind` when given). Without
  `--bind`, all addresses on the queried port are candidates; a
  `<VirtualHost>` argument hostname counts as an alias-like name.
- Merge semantics are module-defined: only the documented
  replace-class (DocumentRoot, ServerName, ErrorLog, CustomLog,
  ServerAdmin, LogLevel, and other plain scalars) gets a plain
  "winner". All other directives report the last merge step with a
  per-module-semantics caveat — the chain is the answer.
- `.htaccess` is never read (AP04). If effective `AllowOverride`
  permits it, directory-scoped answers carry an
  `[htaccess-may-override]` note.
- Conditionals (AP05): `<IfModule>` resolves against the in-tree
  `LoadModule` list; `<IfDefine>` only via `--define`/`Define`
  (otherwise `[define-unknown]`); `<If>`/`<IfVersion>`/`<IfFile>`
  expressions are never evaluated (`[expression-unmodeled]`).
- Out of scope, bannered never claimed (AP07): mod_rewrite outcomes
  (`[rewrite-unmodeled]`), proxy target selection, auth grant
  verdicts, SSL certificate matching, and ServerPath routing.
- Read-only by construction: never runs httpd, never writes, never
  touches the network, never follows a symlink outside `--root` in
  fixture mode (test-asserted: no subprocess, no socket use, reads
  only).

## Pre-publish checklist

- [x] Single-file stdlib CLI, no dependencies
- [x] README with usage, examples, findings, limitations
- [x] Tests: 31 stdlib unittest (30 pass, 1 skip-guarded live
      agreement vs apachectl -S, which needs httpd)
- [x] Zero subprocess, read-only, fixture-root symlink-escape guard —
      test-asserted
- [x] Dogfood: doccover + clicheck
- [x] No secrets, no network, no credentials

## License

MIT (pending Godsby's approval of the license for publication — not
published).
