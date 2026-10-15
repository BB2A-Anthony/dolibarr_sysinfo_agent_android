[app]
title = Dolibarr Sysinfo Agent
package.name = dolibarrsysinfo
package.domain = com.bb2a
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json,txt,ttf

version = 1.0.0

requirements = python3==3.11.8,hostpython3==3.11.8,kivy==2.3.1,requests,psutil,cryptography,android.permissions,android

orientation = portrait

fullscreen = 0

android.permissions = INTERNET,ACCESS_NETWORK_STATE,RECEIVE_BOOT_COMPLETED,FOREGROUND_SERVICE,POST_NOTIFICATIONS,WAKE_LOCK

android.api = 34
android.minapi = 24
android.ndk = 26
android.accept_sdk_license = True
android.antialias = False

services = sysinfo:service.py

# Presplash / icon (optional files)
#android.presplash_filename = presplash.png
#android.icon_filename = icon.png

[buildozer]
log_level = 2
warn_on_root = 1

[mode]
# debug produces a faster build; release APK is signed with the keystore below
#debug = debug
#release = False
