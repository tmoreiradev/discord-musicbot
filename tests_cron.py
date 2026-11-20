#!/usr/bin/env python3
"""Testes dos scripts de cron (stdlib, sem rede, sem Discord): python3 tests_cron.py

Cobrem as falhas reais de 2026-11: chave da Steam revogada derrubando steam-news e wishlist-deals,
rodadas sobrepostas apagando o .tmp do state, post que falha no meio da rodada.
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import botlib

HERE = os.path.dirname(os.path.abspath(__file__))


def load(name):
    """Os scripts tem hifen no nome: carrega pelo caminho."""
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), os.path.join(HERE, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        p = mock.patch.object(botlib, "state_path", lambda n: os.path.join(self.dir.name, f"{n}.json"))
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(botlib, "log", lambda m: None)
        p.start()
        self.addCleanup(p.stop)


class State(Base):
    def test_save_is_atomic_and_leaves_no_tmp(self):
        botlib.save_state("x", {"a": 1})
        self.assertEqual(botlib.load_state("x"), {"a": 1})
        self.assertEqual(os.listdir(self.dir.name), ["x.json"])

    def test_overlapping_runs_do_not_share_tmp(self):
        # a rodada B grava e renomeia enquanto a A ainda esta com o .tmp aberto: antes dava FileNotFoundError
        real_replace = os.replace

        def replace(src, dst):
            if os.getpid() != 999:
                with mock.patch.object(os, "getpid", lambda: 999):
                    botlib.save_state("x", {"who": "B"})
            real_replace(src, dst)
        with mock.patch.object(os, "replace", replace):
            botlib.save_state("x", {"who": "A"})
        self.assertEqual(botlib.load_state("x"), {"who": "A"})

    @unittest.skipIf(sys.platform == "win32", "flock so no Linux")
    def test_single_instance_second_run_exits_zero(self):
        code = ("import botlib,sys,os; botlib.state_path=lambda n: os.path.join(sys.argv[1], n+'.json');"
                "l=botlib.single_instance('s'); print('got', flush=True); sys.stdin.read()")
        a = subprocess.Popen([sys.executable, "-c", code, self.dir.name], cwd=HERE, stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, text=True)
        self.addCleanup(a.kill)  # o primeiro filho nunca sobra vivo, mesmo se o teste falhar no meio
        self.assertEqual(a.stdout.readline().strip(), "got")
        b = subprocess.run([sys.executable, "-c", code, self.dir.name], cwd=HERE, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=20)
        a.communicate("", timeout=20)
        self.assertEqual(b.returncode, 0)
        self.assertNotIn("got", b.stdout.splitlines())


class Steam(Base):
    FC = {"owner": "1", "profiles": ["1", "2"]}

    def test_names_survive_revoked_key(self):
        with mock.patch.object(botlib, "http", side_effect=RuntimeError("HTTP 403 em x")):
            self.assertEqual(botlib.steam_names("k", ["1"]), {})
            self.assertEqual(botlib.steam_profiles("k", self.FC), ["1", "2"])

    def test_no_key_makes_no_request(self):
        with mock.patch.object(botlib, "http") as h:
            self.assertEqual(botlib.steam_names(None, ["1"]), {})
            self.assertEqual(botlib.steam_profiles(None, self.FC), ["1", "2"])
            h.assert_not_called()


class Discord(Base):
    ENV = {"DISCORD_BOT_TOKEN": "t"}

    def test_retries_once_on_429_with_retry_after(self):
        calls = [RuntimeError('HTTP 429 em u: {"message": "rate", "retry_after": 0.25}'), {"id": "1"}]
        with mock.patch.object(botlib, "http", side_effect=calls) as h, mock.patch.object(botlib.time, "sleep") as s:
            self.assertEqual(botlib.discord(self.ENV, "POST", "/x", {}), {"id": "1"})
            self.assertEqual(h.call_count, 2)
            s.assert_called_once_with(0.25)

    def test_does_not_retry_client_error(self):
        with mock.patch.object(botlib, "http", side_effect=RuntimeError("HTTP 404 em u: {}")) as h:
            with self.assertRaises(RuntimeError):
                botlib.discord(self.ENV, "GET", "/x")
            self.assertEqual(h.call_count, 1)

    def test_gives_up_after_second_failure(self):
        with mock.patch.object(botlib, "http", side_effect=RuntimeError("HTTP 503 em u: x")) as h, \
                mock.patch.object(botlib.time, "sleep"):
            with self.assertRaises(RuntimeError):
                botlib.discord(self.ENV, "POST", "/x", {})
            self.assertEqual(h.call_count, 2)


class Http(Base):
    def test_transport_error_becomes_runtime_error(self):
        # URLError/timeout escapavam dos "except RuntimeError" e derrubavam a rodada sem gravar o state
        with mock.patch.object(botlib.urllib.request, "urlopen", side_effect=TimeoutError("timed out")):
            with self.assertRaises(RuntimeError):
                botlib.http("https://x.invalid/a?key=segredo")

    def test_send_carries_nonce_so_retry_cannot_duplicate(self):
        with mock.patch.object(botlib, "http", side_effect=[RuntimeError("HTTP 502 em u: x"), {"id": "1"}]) as h,                 mock.patch.object(botlib.time, "sleep"):
            botlib.send({"DISCORD_BOT_TOKEN": "t"}, "1", [{}])
        first, second = (c.kwargs["data"] for c in h.call_args_list)
        self.assertTrue(first["enforce_nonce"])
        self.assertEqual(first["nonce"], second["nonce"])


class Twitch(Base):
    def test_one_channel_failing_does_not_lose_the_other(self):
        tw = load("twitch-live")
        stream = lambda n: {"id": "s" + n, "user_login": n, "user_name": n, "title": "t", "game_name": "g",
                            "started_at": "2026-11-20T00:00:00Z", "thumbnail_url": "u", "viewer_count": 1}
        helix = lambda env, tok, path, params: [stream("a"), stream("b")] if path == "streams" else []
        send = mock.Mock(side_effect=[{"id": "m1"}, RuntimeError("HTTP 403 em d")])
        with mock.patch.object(tw, "helix", helix), mock.patch.object(tw, "send", send),                 mock.patch.object(tw, "app_token", lambda env, st: "tok"), mock.patch.object(tw, "single_instance"),                 mock.patch.object(tw, "load_env", lambda: {}), mock.patch.object(tw, "log", lambda m: None),                 mock.patch.object(tw, "load_config", lambda: {"twitch": {"channel": "1", "logins": ["a", "b"]}}),                 mock.patch.object(sys, "argv", ["twitch-live.py"]):
            tw.main()
        self.assertEqual(list(botlib.load_state("twitch-live")["lives"]), ["a"])


class GamesWeekly(Base):
    def test_rerun_after_partial_failure_posts_only_what_is_missing(self):
        gw = load("games-weekly")
        http = mock.Mock(side_effect=[{"id": "m1"}, RuntimeError("HTTP 500 em d"), {"id": "m2"}])
        with mock.patch.object(gw, "http", http), mock.patch.object(gw, "twitch_token", lambda *a: "t"), \
                mock.patch.object(gw, "collect", lambda *a: []), \
                mock.patch.object(gw, "build_embeds", lambda *a: [{"description": str(i)} for i in range(15)]), \
                mock.patch.object(gw, "load_env", lambda: {"IGDB_CLIENT_ID": "c", "IGDB_CLIENT_SECRET": "s",
                                                           "GAMES_CHANNEL_ID": "1", "DISCORD_BOT_TOKEN": "t"}), \
                mock.patch.object(sys, "argv", ["games-weekly.py", "--week-of", "2026-11-16"]), \
                mock.patch("builtins.print"):
            with self.assertRaises(RuntimeError):
                gw.main()  # lote 1 sai, lote 2 falha
            gw.main()      # de novo: so o lote 2
            gw.main()      # terceira vez: nada
        self.assertEqual(http.call_count, 3)
        self.assertEqual(botlib.load_state("games-weekly")["sent"], 2)


class SteamNews(Base):
    def setUp(self):
        super().setUp()
        self.sn = load("steam-news")
        for name in ("log", "save_state", "load_state"):
            p = mock.patch.object(self.sn, name, getattr(botlib, name))
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(self.sn.time, "sleep")
        p.start()
        self.addCleanup(p.stop)

    def test_revoked_key_falls_back_to_public_xml(self):
        xml = (b"<steamID><![CDATA[Fulano]]></steamID><gameName><![CDATA[Jogo]]></gameName>"
               b"<gameLink><![CDATA[https://steamcommunity.com/app/42]]></gameLink>")

        def http(url, **kw):
            if "api.steampowered.com" in url:
                raise RuntimeError("HTTP 403 em api")
            return xml
        st = {}
        cfg = {"apps": {}, "friends": {"owner": "1", "profiles": ["1", "2"], "min_players": 1}}
        with mock.patch.object(self.sn, "http", http):
            self.sn.refresh_friends(cfg, st, "revogada")
        self.assertEqual(st["auto_apps"]["42"]["name"], "Jogo")
        self.assertIn("friends_checked", st)

    def test_failed_post_keeps_earlier_success_and_is_retried(self):
        item = lambda gid: {"gid": gid, "title": "Update 1.0", "url": "u", "date": self.sn.now().timestamp(),
                            "contents": "", "tags": []}
        news = {"appnews": {"newsitems": [item("a"), item("b")]}}
        botlib.save_state("steam-news", {"apps": ["7"], "seen": {}, "friends_checked": self.sn.now().isoformat()})
        send = mock.Mock(side_effect=[None, RuntimeError("rede em d: timeout")])
        with mock.patch.object(self.sn, "http", lambda url, **kw: news if "GetNewsForApp" in url else {}), \
                mock.patch.object(self.sn, "send", send), mock.patch.object(self.sn, "single_instance"), \
                mock.patch.object(self.sn, "load_env", lambda: {"GAMES_CHANNEL_ID": "1"}), \
                mock.patch.object(self.sn, "load_config", lambda: {"steam_news": {"apps": {"7": "Jogo"}}}), \
                mock.patch.object(sys, "argv", ["steam-news.py"]):
            self.sn.main()
        self.assertEqual(send.call_count, 2)
        # a postada fica gravada (nao reposta); a que falhou fica de fora (sai na proxima rodada)
        self.assertEqual(list(botlib.load_state("steam-news")["seen"]), ["a"])


if __name__ == "__main__":
    unittest.main()
