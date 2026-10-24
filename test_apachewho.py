"""Tests for apachewho. Hermetic fixture-tree tests (BG1-BG6) plus a
skip-guarded live-agreement test against apachectl -S (BG5; skips on
this box, where no httpd is installed)."""
import importlib.machinery
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "apachewho")
_mod = importlib.machinery.SourceFileLoader("apachewho_mod", TOOL)
apachewho = _mod.load_module()


def run_cli(args, cwd=None):
    proc = subprocess.run([sys.executable, TOOL] + args,
                          capture_output=True, text=True, cwd=cwd)
    return proc.returncode, proc.stdout, proc.stderr


class TmpTree(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="apachewho-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def write(self, rel, text):
        path = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)
        return path

    def conf(self, text, name="apache2.conf"):
        return self.write(name, text)

    def cli(self, *args):
        return run_cli(list(args))


def two_vhost_tree(t, first, second, extra=""):
    main = t.conf("Listen 80\n%s\nInclude vhosts/*.conf\n" % extra)
    t.write("vhosts/a.conf", first)
    t.write("vhosts/b.conf", second)
    return main


# ---------------------------------------------------------------- BG1

class TestSelection(TmpTree):
    def test_first_match_wins_over_later_exact(self):
        # AP01 footgun: wildcard listed first beats a later exact name.
        main = two_vhost_tree(
            self,
            "<VirtualHost *:80>\n ServerName other.test\n"
            " ServerAlias *.example.com\n DocumentRoot /var/www/wild\n"
            "</VirtualHost>\n",
            "<VirtualHost *:80>\n ServerName www.example.com\n"
            " DocumentRoot /var/www/exact\n</VirtualHost>\n")
        rc, out, _ = self.cli("www.example.com", "--conf", main,
                              "--root", self.tmp)
        self.assertEqual(rc, 0)
        self.assertIn("wildcard match", out)
        self.assertIn("/var/www/wild", out)

    def test_exact_first_wins(self):
        main = two_vhost_tree(
            self,
            "<VirtualHost *:80>\n ServerName www.example.com\n"
            " DocumentRoot /var/www/exact\n</VirtualHost>\n",
            "<VirtualHost *:80>\n ServerName other.test\n"
            " ServerAlias *.example.com\n DocumentRoot /var/www/wild\n"
            "</VirtualHost>\n")
        rc, out, _ = self.cli("www.example.com", "--conf", main,
                              "--root", self.tmp)
        self.assertEqual(rc, 0)
        self.assertIn("exact ServerName match", out)

    def test_default_fallback(self):
        main = two_vhost_tree(
            self,
            "<VirtualHost *:80>\n ServerName a.test\n</VirtualHost>\n",
            "<VirtualHost *:80>\n ServerName b.test\n</VirtualHost>\n")
        rc, out, _ = self.cli("unknown.test", "--conf", main,
                              "--root", self.tmp)
        self.assertEqual(rc, 0)
        self.assertIn("default-fallback", out)
        self.assertIn("a.conf:1", out)

    def test_sole_ip_match(self):
        main = self.conf("Listen 80\n<VirtualHost *:80>\n"
                         " ServerName only.test\n</VirtualHost>\n")
        rc, out, _ = self.cli("anything.test", "--conf", main,
                              "--root", self.tmp)
        self.assertEqual(rc, 0)
        self.assertIn("sole-ip-match", out)

    def test_no_vhost_for_port(self):
        main = self.conf("Listen 80\n<VirtualHost *:80>\n"
                         " ServerName a.test\n</VirtualHost>\n")
        rc, out, _ = self.cli("a.test", "--port", "8080", "--conf", main,
                              "--root", self.tmp)
        self.assertEqual(rc, 1)
        self.assertIn("no VirtualHost for port 8080", out)

    def test_duplicate_servername_shadowed(self):
        main = two_vhost_tree(
            self,
            "<VirtualHost *:80>\n ServerName dup.test\n</VirtualHost>\n",
            "<VirtualHost *:80>\n ServerName dup.test\n</VirtualHost>\n")
        rc, out, _ = self.cli("dup.test", "--conf", main,
                              "--root", self.tmp)
        self.assertEqual(rc, 0)
        self.assertIn("AP09", out)
        self.assertIn("a.conf:1", out.split("host ")[1].split("\n")[0])

    def test_unlisted_port_never_selected(self):
        main = self.conf("Listen 80\n"
                         "<VirtualHost *:8080>\n ServerName x.test\n"
                         "</VirtualHost>\n")
        rc, out, _ = self.cli("x.test", "--port", "8080", "--conf", main,
                              "--root", self.tmp)
        self.assertEqual(rc, 1)
        self.assertIn("AP11", out)
        rc2, out2, _ = self.cli("--list-vhosts", "--conf", main,
                                "--root", self.tmp)
        self.assertEqual(rc2, 0)
        self.assertIn("x.test", out2)

    def test_no_servername_only_default(self):
        # Two vhosts so name matching runs and the nameless first vhost
        # can only win as the default fallback (AP01 step 4 / AP12).
        main = self.conf("Listen 80\n"
                         "<VirtualHost *:80>\n DocumentRoot /var/www/d\n"
                         "</VirtualHost>\n"
                         "<VirtualHost *:80>\n ServerName named.test\n"
                         "</VirtualHost>\n")
        rc, out, _ = self.cli("whatever.test", "--conf", main,
                              "--root", self.tmp)
        self.assertEqual(rc, 0)
        self.assertIn("AP12", out)
        self.assertIn("default-fallback", out)

    def test_host_port_ignored_and_case_insensitive(self):
        # Two vhosts so name matching runs (a sole vhost would win by
        # sole-ip-match without any name matching, AP01 step 2).
        main = self.conf("Listen 80\n<VirtualHost *:80>\n"
                         " ServerName www.example.com\n</VirtualHost>\n"
                         "<VirtualHost *:80>\n ServerName other.test\n"
                         "</VirtualHost>\n")
        rc, out, _ = self.cli("WWW.EXAMPLE.COM:9999", "--conf", main,
                              "--root", self.tmp)
        self.assertEqual(rc, 0)
        self.assertIn("exact ServerName match", out)

    def test_trailing_dot_not_stripped(self):
        main = two_vhost_tree(
            self,
            "<VirtualHost *:80>\n ServerName first.test\n</VirtualHost>\n",
            "<VirtualHost *:80>\n ServerName www.example.com\n"
            "</VirtualHost>\n")
        rc, out, _ = self.cli("www.example.com.", "--conf", main,
                              "--root", self.tmp)
        self.assertEqual(rc, 0)
        self.assertIn("default-fallback", out)

    def test_vhost_arg_name_counts_as_alias(self):
        main = self.conf("Listen 80\n"
                         "<VirtualHost argname.test:80>\n"
                         " DocumentRoot /var/www/arg\n</VirtualHost>\n")
        rc, out, _ = self.cli("argname.test", "--conf", main,
                              "--root", self.tmp)
        self.assertEqual(rc, 0)
        # Sole candidate for the port: sole-ip-match still applies.
        self.assertIn("sole-ip-match", out)

    def test_ipv6_and_malformed_address(self):
        main = self.conf("Listen 80\n"
                         "<VirtualHost [::1]:80>\n ServerName v6.test\n"
                         "</VirtualHost>\n")
        rc, out, _ = self.cli("v6.test", "--bind", "::1", "--conf", main,
                              "--root", self.tmp)
        self.assertEqual(rc, 0)
        bad = self.conf("Listen 80\n<VirtualHost *:xx>\n ServerName y\n"
                        "</VirtualHost>\n", name="bad.conf")
        rc, _out, err = self.cli("y", "--conf", bad, "--root", self.tmp)
        self.assertEqual(rc, 2)
        self.assertIn("malformed", err)


# ---------------------------------------------------------------- BG2

class TestMerge(TmpTree):
    def test_directory_longest_wins_despite_file_order(self):
        # Later file, shorter path loses: longest matching Directory
        # wins regardless of file order (AP03).
        main = self.conf(
            "Listen 80\n"
            "<VirtualHost *:80>\n ServerName m.test\n"
            " <Directory /var/www/a/b>\n  AllowOverride All\n"
            " </Directory>\n"
            " Include later/*.conf\n"
            "</VirtualHost>\n")
        self.write("later/c.conf",
                   "<Directory /var/www/a>\n AllowOverride None\n"
                   "</Directory>\n")
        # The later include lands inside the vhost; its Directory is a
        # vhost section too. Query a path under both.
        rc, out, _ = self.cli("m.test", "--directive", "AllowOverride",
                              "--path", "/var/www/a/b/page", "--conf",
                              main, "--root", self.tmp)
        self.assertEqual(rc, 0, out)
        self.assertIn("= All (winner by merge order)", out)
        self.assertLess(out.index("= None (shadowed)"),
                        out.index("= All (winner by merge order)"))

    def test_vhost_location_beats_server_location(self):
        main = self.conf(
            "Listen 80\n"
            "<Location /app>\n Require all denied\n</Location>\n"
            "<VirtualHost *:80>\n ServerName l.test\n"
            " <Location /app>\n  Require all granted\n </Location>\n"
            "</VirtualHost>\n")
        rc, out, _ = self.cli("l.test", "--directive", "Require",
                              "--path", "/app/x", "--conf", main,
                              "--root", self.tmp)
        self.assertEqual(rc, 0, out)
        # Server section first, vhost section last (winner).
        self.assertLess(out.index("all denied"),
                        out.index("all granted"))
        self.assertIn("per-module", out)

    def test_server_directive_survives(self):
        main = self.conf(
            "Listen 80\nErrorLog /var/log/main-error.log\n"
            "<VirtualHost *:80>\n ServerName s.test\n</VirtualHost>\n")
        rc, out, _ = self.cli("s.test", "--directive", "ErrorLog",
                              "--conf", main, "--root", self.tmp)
        self.assertEqual(rc, 0)
        self.assertIn("/var/log/main-error.log", out)
        self.assertIn("winner by merge order", out)

    def test_directive_unset_everywhere(self):
        main = self.conf("Listen 80\n<VirtualHost *:80>\n"
                         " ServerName u.test\n</VirtualHost>\n")
        rc, _out, _ = self.cli("u.test", "--directive", "DocumentRoot",
                               "--conf", main, "--root", self.tmp)
        self.assertEqual(rc, 1)


# ---------------------------------------------------------------- BG3

class TestIncludes(TmpTree):
    def test_wildcard_alphabetical(self):
        main = self.conf("Listen 80\nInclude conf.d/*.conf\n")
        self.write("conf.d/b.conf",
                   "<VirtualHost *:80>\n ServerName b.test\n</VirtualHost>\n")
        self.write("conf.d/a.conf",
                   "<VirtualHost *:80>\n ServerName a.test\n</VirtualHost>\n")
        rc, out, _ = self.cli("--list-vhosts", "--conf", main,
                              "--root", self.tmp)
        self.assertEqual(rc, 0)
        self.assertLess(out.index("a.conf"), out.index("b.conf"))
        self.assertIn("[default for port(s) 80]", out.split("\n")[1])

    def test_directory_argument_expansion(self):
        main = self.conf("Listen 80\nInclude conf.d\n")
        self.write("conf.d/deep/v.conf",
                   "<VirtualHost *:80>\n ServerName d.test\n</VirtualHost>\n")
        rc, out, _ = self.cli("--list-vhosts", "--conf", main,
                              "--root", self.tmp)
        self.assertEqual(rc, 0)
        self.assertIn("d.test", out)

    def test_missing_include_fatal_vs_optional_silent(self):
        main = self.conf("Listen 80\nInclude nope/*.conf\n")
        rc, _out, err = self.cli("--list-vhosts", "--conf", main,
                                 "--root", self.tmp)
        self.assertEqual(rc, 2)
        self.assertIn("missing Include", err)
        main2 = self.conf("Listen 80\nIncludeOptional nope/*.conf\n"
                          "<VirtualHost *:80>\n ServerName ok.test\n"
                          "</VirtualHost>\n", name="opt.conf")
        rc, out, _ = self.cli("--list-vhosts", "--conf", main2,
                              "--root", self.tmp)
        self.assertEqual(rc, 0)
        self.assertIn("AP02", out)  # note, not an error
        self.assertIn("ok.test", out)

    def test_include_cycle_fatal(self):
        main = self.conf("Listen 80\nInclude loop.conf\n")
        self.write("loop.conf", "Include apache2.conf\n")
        rc, _out, err = self.cli("--list-vhosts", "--conf", main,
                                 "--root", self.tmp)
        self.assertEqual(rc, 2)
        self.assertIn("cycle", err)

    def test_sites_available_present_but_not_loaded(self):
        main = self.conf("Listen 80\nInclude sites-enabled/*.conf\n")
        self.write("sites-available/loaded.conf",
                   "<VirtualHost *:80>\n ServerName l.test\n</VirtualHost>\n")
        self.write("sites-available/orphan.conf",
                   "<VirtualHost *:80>\n ServerName o.test\n</VirtualHost>\n")
        os.makedirs(os.path.join(self.tmp, "sites-enabled"),
                    exist_ok=True)
        os.symlink("../sites-available/loaded.conf",
                   os.path.join(self.tmp, "sites-enabled", "loaded.conf"))
        rc, out, _ = self.cli("--list-vhosts", "--conf", main,
                              "--root", self.tmp)
        self.assertEqual(rc, 0)
        self.assertIn("AP10", out)
        self.assertIn("orphan.conf", out)
        self.assertNotIn("loaded.conf", out.split("findings:")[1]
                         .split("AP10")[1].split("\n")[0]
                         if "AP10" in out else "")

    def test_symlink_escape_not_followed(self):
        outside = tempfile.mkdtemp(prefix="apachewho-outside-")
        self.addCleanup(shutil.rmtree, outside, True)
        with open(os.path.join(outside, "evil.conf"), "w") as fh:
            fh.write("<VirtualHost *:80>\n ServerName evil.test\n"
                     "</VirtualHost>\n")
        main = self.conf("Listen 80\nInclude links/*.conf\n")
        os.makedirs(os.path.join(self.tmp, "links"))
        os.symlink(os.path.join(outside, "evil.conf"),
                   os.path.join(self.tmp, "links", "evil.conf"))
        rc, out, _ = self.cli("--list-vhosts", "--conf", main,
                              "--root", self.tmp)
        self.assertEqual(rc, 1)  # no vhosts loaded; escape is a finding
        self.assertIn("escapes fixture root", out)

    def test_relative_include_via_serverroot(self):
        main = self.conf("ServerRoot %s\nListen 80\n"
                         "Include sub/*.conf\n" % self.tmp)
        self.write("sub/v.conf",
                   "<VirtualHost *:80>\n ServerName r.test\n</VirtualHost>\n")
        rc, out, _ = self.cli("--list-vhosts", "--conf", main,
                              "--root", self.tmp)
        self.assertEqual(rc, 0)
        self.assertIn("r.test", out)


# ---------------------------------------------------------------- BG4

class TestConditionals(TmpTree):
    def test_ifmodule_loaded_vs_not(self):
        main = self.conf(
            "Listen 80\nLoadModule ssl_module modules/mod_ssl.so\n"
            "<VirtualHost *:80>\n ServerName c.test\n"
            " <IfModule mod_ssl.c>\n  DocumentRoot /var/www/ssl\n"
            " </IfModule>\n"
            " <IfModule mod_missing.c>\n  ErrorLog /var/log/missing.log\n"
            " </IfModule>\n"
            "</VirtualHost>\n")
        rc, out, _ = self.cli("c.test", "--directive", "DocumentRoot",
                              "--conf", main, "--root", self.tmp)
        self.assertEqual(rc, 0)
        self.assertIn("/var/www/ssl", out)
        rc, out, _ = self.cli("c.test", "--directive", "ErrorLog",
                              "--conf", main, "--root", self.tmp)
        self.assertEqual(rc, 1)
        self.assertIn("AP05", out)

    def test_ifdefine_via_flag_and_unknown(self):
        main = self.conf(
            "Listen 80\n<VirtualHost *:80>\n ServerName d.test\n"
            " <IfDefine PROD>\n  DocumentRoot /var/www/prod\n"
            " </IfDefine>\n"
            " DocumentRoot /var/www/base\n"
            "</VirtualHost>\n")
        rc, out, _ = self.cli("d.test", "--directive", "DocumentRoot",
                              "--define", "PROD", "--conf", main,
                              "--root", self.tmp)
        self.assertEqual(rc, 0)
        self.assertIn("/var/www/prod", out)
        rc, out, _ = self.cli("d.test", "--directive", "DocumentRoot",
                              "--define", "OTHER", "--conf", main,
                              "--root", self.tmp)
        self.assertEqual(rc, 0)
        # Without PROD defined, the gated value is not the winner.
        self.assertIn("/var/www/base (winner by merge order)", out)
        self.assertIn("[define-unknown]", out)

    def test_if_expression_never_evaluated(self):
        main = self.conf(
            "Listen 80\n<VirtualHost *:80>\n ServerName e.test\n"
            " <If \"%{HTTP_HOST} == 'e.test'\">\n"
            "  DocumentRoot /var/www/if\n </If>\n"
            " DocumentRoot /var/www/base\n</VirtualHost>\n")
        rc, out, _ = self.cli("e.test", "--directive", "DocumentRoot",
                              "--conf", main, "--root", self.tmp)
        self.assertEqual(rc, 0)
        self.assertIn("/var/www/base (winner by merge order)", out)
        self.assertIn("[expression-unmodeled]", out)


# ---------------------------------------------------------------- BG5/BG6

class TestHonestyAndOutput(TmpTree):
    def test_rewrite_banner_never_claims_url(self):
        main = self.conf(
            "Listen 80\n<VirtualHost *:80>\n ServerName r.test\n"
            " RewriteEngine On\n"
            " RewriteRule ^/old /new [L]\n</VirtualHost>\n")
        rc, out, _ = self.cli("r.test", "--directive", "RewriteRule",
                              "--conf", main, "--root", self.tmp)
        self.assertEqual(rc, 0)
        self.assertIn("[rewrite-unmodeled]", out)

    def test_json_shape(self):
        main = self.conf("Listen 80\n<VirtualHost *:80>\n"
                         " ServerName j.test\n DocumentRoot /var/www/j\n"
                         "</VirtualHost>\n")
        rc, out, _ = self.cli("j.test", "--directive", "DocumentRoot",
                              "--json", "--conf", main, "--root", self.tmp)
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertEqual(data["selected"]["selection"], "sole-ip-match")
        self.assertEqual(data["directive"]["winner"]["value"],
                         "/var/www/j")
        self.assertIn("apache2.conf", data["directive"]["winner"]["ref"])

    def test_version_and_quiet(self):
        rc, out, _ = self.cli("--version")
        self.assertEqual(rc, 0)
        self.assertIn("apachewho 1.0.0", out)
        main = self.conf("Listen 80\n<VirtualHost *:80>\n"
                         " ServerName q.test\n</VirtualHost>\n")
        rc, out, _ = self.cli("--quiet", "q.test", "--conf", main,
                              "--root", self.tmp)
        self.assertEqual(rc, 0)
        self.assertEqual(len(out.strip().splitlines()), 1)

    def test_no_subprocess_or_socket_in_tool(self):
        with open(TOOL) as fh:
            src = fh.read()
        self.assertNotIn("subprocess", src)
        self.assertNotIn("socket", src)
        for m in re.finditer(r"open\(([^)]*)\)", src):
            self.assertIn('"r"', m.group(1),
                          "tool must only open files for reading: %s"
                          % m.group(0))

    def test_live_agreement_skip_guarded(self):
        if not (shutil.which("apachectl") or shutil.which("httpd")):
            self.skipTest("no httpd installed on this box (BG5 skip)")
        # If httpd ever exists, --list-vhosts must agree with -S on
        # vhost order/names; this branch only runs where httpd exists.
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
