# Dolibarr Sysinfo Agent Android

Agent Python qui collecte les informations système d'un appareil Android et les envoie périodiquement à l'API du module Dolibarr `systeminfo` (même protocole que l'agent Windows). Il fonctionne sous [Termux](https://termux.dev), sans root.

## Versions minimales et maximales

| Composant | Version minimale | Version maximale (testée) | Notes |
|---|---|---|---|
| Android | 7.0 (API 24) | 15 (API 35) | Termux cesse officiellement de supporter Android < 7 ; certaines commandes `getprop` peuvent être restreintes sur Android ≥ 13 sans shell complet |
| Termux | 0.118 (F-Droid) | 0.118.x | La version Play Store est obsolète, utiliser [F-Droid](https://f-droid.org/packages/com.termux/) ou GitHub |
| Termux:API | 0.50 | 0.50.x | Pour la batterie via `termux-battery-status` (optionnel) |
| Python | 3.9 | 3.13 | `pkg install python` sous Termux fournit une version dans cet intervalle ; les constructions `python` et `python-pt3` de Termux conviennent |
| requests | 2.31.0 | 2.32.x | Dépendance HTTP |
| psutil | 5.9.0 | 6.1.x | CPU, mémoire, disques, réseau ; compatible Termux sans root |
| cryptography | 41.0.0 | 44.x | Chiffrement AES-GCM de la clé API ; en dessous de 41, l'agent retombe sur un stockage en clair de la clé |
| Module Dolibarr `systeminfo` | identique à l'agent Windows (`dolibarr_sysinfo_agent_windows/server_module`) | — | Aucune modification serveur requise |

Les versions au-dessus de la version maximale indiquée ne sont pas testées : l'agent devrait fonctionner, mais sans garantie. En cas d'incompatibilité, se référer aux [issues du dépôt](https://github.com/BB2A-Anthony/dolibarr_sysinfo_agent_android/issues).

## Informations collectées

- Hostname, FQDN, architecture, processeur, version Python
- Android : modèle, marque, fabricant, version Android, SDK, patch de sécurité, build, émulateur détecté (via `getprop`)
- CPU (cœurs logiques/physiques, utilisation)
- Mémoire (totale, disponible, utilisée, %)
- Stockage (par partition : total, utilisé, libre, %)
- Interfaces réseau (adresses IPv4/IPv6) et adresses MAC
- Temps de démarrage et uptime
- Batterie : %, charge, température, santé (via Termux:API ou `/sys/class/power_supply`)
- IP publique et FAI (best effort)

## Installation (Termux)

1. Installer Termux (F-Droid recommandé) puis :

   ```bash
   pkg update
   pkg install -y python termux-api
   git clone <ce depot>
   cd dolibarr_sysinfo_agent_android
   python -m pip install -r requirements.txt
   cp config.example.json config.json
   ```

2. Adapter `config.json` :

   ```json
   {
       "api_url": "https://dolibarr.example.com",
       "initial_delay_seconds": 30,
       "poll_interval_seconds": 14400,
       "timeout_seconds": 30,
       "verify_ssl": true
   }
   ```

   | Clé | Rôle |
   |---|---|
   | `api_url` | URL de base du Dolibarr (l'agent ajoute `/api/index.php/systeminfo/machine`) |
   | `guid` | Identifiant de l'appareil, généré automatiquement (numéro de série Android) — ne se configure normalement pas |
   | `api_key` / `api_key_encrypted` | Clé API Dolibarr (chiffrée automatiquement en AES-GCM lié à l'appareil) |
   | `poll_interval_seconds` | Intervalle entre deux envois (par défaut 14400 s = 4 h) |
   | `auto_update` | Mise à jour automatique activée (par défaut true, voir ci-dessous) |

## Mise à jour automatique

L'agent vérifie sa version après chaque envoi de rapport en interrogeant le module Dolibarr `systeminfo` (`GET /api/index.php/sysinfo/config`), qui expose la dernière version disponible et l'URL du dossier de mise à jour sur GitHub (`releases/download/<version>/update/`). Si la version distante est plus récente, l'APK `dolibarr_sysinfo_agent.apk` est téléchargé ; sur Android une application ne peut pas se remplacer elle-même silencieusement, l'installation doit donc être confirmée par l'utilisateur (bouton « Vérifier la mise à jour » de l'UI, ou intent système lancé au moment du téléchargement).

Pour désactiver ce comportement : `"auto_update": false` dans `config.json`.

Côté serveur, la version publiée se règle dans le descripteur du module (`agentAndroidVersion` / `agentAndroidUpdateUrl`) ou via les constantes `SYSINFO_AGENT_ANDROID_VERSION` / `SYSINFO_AGENT_ANDROID_UPDATE_URL`.

## Utilisation

```bash
# Envoi unique
python run.py --config config.json

# Envoi en boucle
python run.py --config config.json --loop

# Enrôlement avec un code à usage unique (généré sur la fiche tiers Dolibarr)
python run.py --enroll ABC123

# Stocker la clé API chiffrée
python run.py --set-api-key VOTRE_CLE
```

Ou via le script `./run.sh [--loop]` (installe Python et les dépendances si besoin).

Pour que la batterie soit rapportée via l'API Termux, installer l'application compagnon **Termux:API** (F-Droid) et le paquet `termux-api`. Sans Termux:API, l'agent retombe sur `/sys/class/power_supply`.

## Envoi périodique automatique

Termux ne fournit pas de service système natif à un utilisateur non-root ; les options recommandées :

- laisser `python run.py --loop` tourner dans une session Termux, avec `termux-wake-lock` pour éviter l'endormissement ;
- utiliser `crond` (`pkg install cronie termux-services`) avec un job `0 */4 * * * cd ~/dolibarr_sysinfo_agent_android && python run.py`.

## Sécurité

- La clé API est stockée chiffrée (AES-GCM, clé dérivée des propriétés matérielles de l'appareil via PBKDF2) : `config.json` ne contient jamais la clé en clair une fois migrée.
- Si le paquet `cryptography` n'est pas installable, l'agent retombe sur un stockage en clair (équivalent à l'agent Windows hors DPAPI).
- Le module serveur `systeminfo` côté Dolibarr est le même que pour l'agent Windows (voir `dolibarr_sysinfo_agent_windows/server_module`).

## Compatibilité serveur

Le payload est identique à celui de l'agent Windows (mêmes champs `guid`, `hostname`, `memory`, `disks`, `network_interfaces`, `cpu`, ...) plus un champ `battery` spécifique à Android et `os_details` contenant les propriétés Android. Le champ Android est simplement ignoré côté serveur si non pris en charge.

## Application Android native (APK)

En plus du mode Termux, l'agent est disponible en **APK autonome** (code Python partagé, UI Kivy, service en arrière-plan), pour une installation simple sans manipulation technique :

1. Télécharger l'APK depuis la page **Actions** du dépôt (workflow « Build Android APK » → dernière exécution → artifact `dolibarr-sysinfo-agent-apk`).
2. Installer l'APK sur l'appareil (autoriser « sources inconnues »).
3. Ouvrir l'application et renseigner :
   - l'URL Dolibarr (ex. `https://dolibarr.example.com`) ;
   - le **code d'enrôlement** à usage unique généré sur la fiche tiers Dolibarr.
4. Taper « Enrôler l'appareil » : la clé API est récupérée et stockée chiffrée (AES-GCM lié à l'appareil). « Envoyer maintenant » force un premier rapport ; « Tester la connexion » vérifie l'accès à l'API.

L'envoi périodique est assuré par le service embarqué `sysinfo` (`service.py`) : il démarre au boot de l'appareil et envoie un rapport toutes les `poll_interval_seconds` (par défaut 4 h). Sur Android moderne, exempter l'app de l'optimisation de batterie (une invite s'affiche) pour un envoi fiable.

Le build APK utilise [Buildozer](https://buildozer.readthedocs.io) (`buildozer.spec`) et est automatisé par GitHub Actions (`.github/workflows/build-apk.yml`) : chaque push reconstruit l'APK et le publie en artifact. Le payload envoyé est strictement identique à celui de l'agent Termux/Windows.
