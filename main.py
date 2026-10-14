"""Kivy UI for the Dolibarr Sysinfo Agent (Android APK).

Simple installation flow:
1. Enter the Dolibarr base URL
2. Enter the one-time enrollment code from the thirdparty card
3. Tap "Enroll" - the API key is fetched and stored encrypted
4. The periodic background service sends system reports

Reuses agent/ (collector, sender, crypto) from the Termux agent.
"""
import json
import logging
import os
import threading

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.properties import StringProperty
from kivy.uix.boxlayout import BoxLayout

from mobile_common import config_path, ensure_config

from agent.sender import enroll_soc, load_config, send_report, test_connection

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sysinfo.app")

Builder.load_string("""
<AgentLayout>:
    orientation: "vertical"
    padding: dp(16)
    spacing: dp(12)

    Label:
        text: "Agent Sysinfo Dolibarr"
        font_size: dp(22)
        bold: True
        size_hint_y: None
        height: dp(32)

    Label:
        text: "URL Dolibarr (ex: https://dolibarr.example.com)"
        size_hint_y: None
        height: dp(20)
        halign: "left"

    TextInput:
        id: url_input
        multiline: False
        hint_text: "https://dolibarr.example.com"
        size_hint_y: None
        height: dp(44)

    Label:
        text: "Code d'enrolement (fiche tiers Dolibarr)"
        size_hint_y: None
        height: dp(20)
        halign: "left"

    TextInput:
        id: enroll_input
        multiline: False
        hint_text: "ABC123"
        size_hint_y: None
        height: dp(44)

    Button:
        text: "Enroler l'appareil"
        size_hint_y: None
        height: dp(48)
        on_press: root.do_enroll()

    Button:
        text: "Envoyer maintenant"
        size_hint_y: None
        height: dp(48)
        on_press: root.do_send_now()

    Button:
        text: "Tester la connexion"
        size_hint_y: None
        height: dp(48)
        on_press: root.do_test()

    Label:
        id: status_label
        text: root.status_text
        size_hint_y: None
        height: dp(200)
        valign: "top"
        halign: "left"
        text_size: self.width, None
""")


class AgentLayout(BoxLayout):
    status_text = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._busy = False
        ensure_config()
        Clock.schedule_once(lambda dt: self.refresh_status(), 0.5)

    def refresh_status(self):
        try:
            path = config_path()
            config = load_config(path)
            enrolled = bool(config.get("api_key_encrypted") or config.get("api_key"))
            interval = config.get("poll_interval_seconds", 14400)
            status = [
                "GUID: %s" % config.get("guid", "?"),
                "Enrole: %s" % ("oui" if enrolled else "non"),
                "Intervalle: %s h" % max(1, interval // 3600),
            ]
            if config.get("api_url"):
                status.append("URL: %s" % config["api_url"])
            self.status_text = "\n".join(status)
        except Exception as exc:
            self.status_text = "Erreur config: %s" % exc

    def _run_bg(self, fn):
        def worker():
            try:
                result = fn()
            except Exception as exc:
                result = "Erreur: %s" % exc
            Clock.schedule_once(lambda dt: self._done(result), 0)
        threading.Thread(target=worker, daemon=True).start()

    def _done(self, result):
        self._busy = False
        self.status_text = str(result)

    def do_enroll(self):
        if self._busy:
            return
        url = self.ids.url_input.text.strip()
        code = self.ids.enroll_input.text.strip()
        if not url or not code:
            self.status_text = "URL et code requis."
            return
        self._busy = True
        self.status_text = "Enrolement en cours..."
        path = config_path()
        self._run_bg(lambda: self._enroll(url, code, path, confirm=False))

    def _enroll(self, url, code, path, confirm):
        config = load_config(path)
        config["api_url"] = url
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
        ok, message, need_confirm = enroll_soc(config, code, path, confirm_reassign=confirm)
        if need_confirm:
            ok2, message2, _ = enroll_soc(config, code, path, confirm_reassign=True)
            return message + "\n" + message2
        return message

    def do_send_now(self):
        if self._busy:
            return
        self._busy = True
        self.status_text = "Collecte et envoi en cours..."
        self._run_bg(lambda: self._send())

    def _send(self):
        config = load_config(config_path())
        send_report(config)
        return "Rapport envoye avec succes."

    def do_test(self):
        if self._busy:
            return
        self._busy = True
        self.status_text = "Test de connexion en cours..."
        self._run_bg(lambda: test_connection(load_config(config_path()))[1])


class SysinfoApp(App):
    def build(self):
        Window.softinput_mode = "below_target"
        return AgentLayout()


if __name__ == "__main__":
    SysinfoApp().run()
