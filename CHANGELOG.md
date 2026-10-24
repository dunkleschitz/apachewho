# CHANGELOG — apachewho

## 1.0.0 (2026-10-24)

Initial release. Static model of httpd 2.4's documented VirtualHost
selection and section-merge rules: which vhost handles Host X, and
which file:line set each effective directive for it.

AP01 vhost selection (IP:port first, first name match in config order
with no wildcard/exact precedence, first vhost as default fallback,
sole-vhost short-circuit, VirtualHost-argument names as aliases);
AP02 in-place Include/IncludeOptional expansion (alphabetical
wildcards, directory expansion, ServerRoot-relative paths, missing
Include fatal vs missing IncludeOptional silent, cycle fatal, fixture
-root symlink-escape guard); AP03 merge chain (main server, then
vhost, then Directory-shortest-first / DirectoryMatch / Files /
Location / If groups, server sections before vhost sections, with a
documented replace-class for plain winners and a per-module-semantics
caveat for everything else); AP04 .htaccess never read, bannered via
AllowOverride; AP05 conditionals gated (IfModule vs in-tree LoadModule
list, IfDefine only via --define/Define, <If> never evaluated);
AP06 case-insensitive fnmatch name matching, verbatim trailing dot,
IPv6 literals; AP07 rewrite/proxy/auth/SSL verdicts bannered, never
claimed; AP09 duplicate-name shadowing, AP10 present-but-not-loaded
(Debian sites-available), AP11 unlisted-port vhosts, AP12
no-ServerName vhosts. Exit 0/1/2; --json/--quiet/--list-vhosts.

Claims are [documented]/[docs-inferred] only — no httpd on the build
box, so live-agreement tests vs apachectl -S are skip-guarded (BG5).

31 tests (stdlib unittest), 30 pass + 1 skip; zero-subprocess,
read-only, and fixture-root escape guard are test-asserted. Dogfood:
doccover 12/12, clicheck 15/15.

Build corrections during v1: section-tag parsing fixed for tags with
arguments (token-based detection missed `<Directory /path>`); IfDefine
without its own flag is [define-unknown] per the design, never
treated as proof of undefined.
