[app]
title = NTE Wish Tracker
package.name = ntewishtracker
package.domain = org.nte
source.dir = .
source.include_exts = py,png,jpg,kv,json,traineddata,mp3,ogg,wav,ttf
source.include_patterns = assets/*,assets/*/*,tessdata/*
source.exclude_dirs = tests,tools,bin,.buildozer,__pycache__,.git
version = 0.1.0

requirements = python3==3.11.5,hostpython3==3.11.5,kivy==2.3.0,numpy,pillow,opencv,pyjnius,android,certifi,androidstorage4kivy

p4a.branch = v2024.01.21

orientation = portrait
fullscreen = 0

android.permissions = INTERNET
android.api = 34
android.minapi = 29
android.ndk = 25b
android.archs = arm64-v8a
android.accept_sdk_license = True
android.enable_androidx = True

android.gradle_dependencies = cz.adaptech.tesseract4android:tesseract4android:4.9.0
android.add_gradle_repositories = "maven { url 'https://jitpack.io' }"

presplash.color = #0d0f1d

[buildozer]
log_level = 2
warn_on_root = 1
