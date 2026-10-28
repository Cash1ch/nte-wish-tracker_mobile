[app]
title = NTE Wish Tracker
package.name = ntewishtracker
package.domain = org.nte
source.dir = .
source.include_exts = py,png,jpg,kv,json,traineddata,mp3,ogg,wav,ttf
source.include_patterns = assets/*,assets/*/*,tessdata/*
source.exclude_dirs = tests,tools,bin,.buildozer,__pycache__,.git
version = 0.1.0

# opencv — самый капризный рецепт p4a; без него nte_core сам переключится на конвейер Pillow
# (ocr_image -> _ocr_pipeline_pil), но точность будет ниже.
requirements = python3,kivy==2.3.0,numpy,pillow,opencv,pyjnius,android,certifi,androidstorage4kivy

orientation = portrait
fullscreen = 0

# Android 10+: SAF-выбор файлов и MediaStore не требуют разрешений на хранилище и камеру.
android.permissions = INTERNET
android.api = 34
android.minapi = 29
android.ndk = 25b
android.archs = arm64-v8a
android.accept_sdk_license = True
android.enable_androidx = True

# Tesseract4Android (Tesseract 5.x + Leptonica, rus/eng берутся из tessdata/ в APK).
# Версию сверьте на https://github.com/adaptech-cz/Tesseract4Android
android.gradle_dependencies = cz.adaptech.tesseract4android:tesseract4android:4.9.0

# bundle: icons -> assets/icons, music -> assets/audio/bgm.mp3, tessdata/*.traineddata
presplash.color = #0d0f1d

[buildozer]
log_level = 2
warn_on_root = 1
