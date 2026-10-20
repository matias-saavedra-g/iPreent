# Sesiones de prueba manuales

Este documento contiene la serie de pruebas que realiza el usuario de forma manual con su propia impresora, siendo unbranded y con ID de Bluetooth `SC03h-5363`.

Las entradas del presente documento tienen el formato "## YYYY.MM.DD.hh.mm ${Title}".

## 2026.10.13.22.34 Prueba de Python CLI

El entorno de pruebas es un Thinkpad L14 Gen 2 con Windows 11 Pro 25H2. En la prueba de hoy se ejecutaron dos acciones:

1. Probar la conexión automática tan solo pidiendo imprimir texto y que el programa + Windows se conectasen, se requirió intervención manual para conectarse a la impresora pues hubo una solicitud de emparejamiento de Windows: la cual resultó fue exitosa.
2. Probar la conexión automática a través del protocolo Bluetooth Low Energy, y esta vez no hubo intervención del usuario, desconozco si era porque ya estaba emparejado o BLE no eleva una solicitud de por sí: también resultó exitosa.

Se adjunta el log de ejecución de las dos pruebas a continuación.

```log
PowerShell 7.6.6
PS C:\Users\mattia> cd '.\Documents\Projects\ipreent\'
PS C:\Users\mattia\Documents\Projects\ipreent> python -m venv venv
PS C:\Users\mattia\Documents\Projects\ipreent> .\venv\Scripts\activate
(venv) PS C:\Users\mattia\Documents\Projects\ipreent> pip install .
Processing .\.
  Installing build dependencies ... done
  Getting requirements to build wheel ... done
  Preparing metadata (pyproject.toml) ... done
Collecting bleak>=0.22 (from ipreent==0.1.0)
  Downloading bleak-3.0.2-py3-none-any.whl.metadata (4.7 kB)
Collecting Pillow>=10 (from ipreent==0.1.0)
  Downloading pillow-12.3.0-cp314-cp314-win_amd64.whl.metadata (9.3 kB)
Collecting pyserial>=3.5 (from ipreent==0.1.0)
  Downloading pyserial-3.5-py2.py3-none-any.whl.metadata (1.6 kB)
Collecting pypdfium2>=4 (from ipreent==0.1.0)
  Downloading pypdfium2-5.14.0-py3-none-win_amd64.whl.metadata (63 kB)
Collecting winrt-runtime>=3.1 (from bleak>=0.22->ipreent==0.1.0)
  Downloading winrt_runtime-3.2.1-cp314-cp314-win_amd64.whl.metadata (780 bytes)
Collecting winrt-windows-devices-bluetooth>=3.1 (from bleak>=0.22->ipreent==0.1.0)
  Downloading winrt_windows_devices_bluetooth-3.2.1-cp314-cp314-win_amd64.whl.metadata (1.6 kB)
Collecting winrt-windows-devices-bluetooth-advertisement>=3.1 (from bleak>=0.22->ipreent==0.1.0)
  Downloading winrt_windows_devices_bluetooth_advertisement-3.2.1-cp314-cp314-win_amd64.whl.metadata (1.4 kB)
Collecting winrt-windows-devices-bluetooth-genericattributeprofile>=3.1 (from bleak>=0.22->ipreent==0.1.0)
  Downloading winrt_windows_devices_bluetooth_genericattributeprofile-3.2.1-cp314-cp314-win_amd64.whl.metadata (1.5 kB)
Collecting winrt-windows-devices-enumeration>=3.1 (from bleak>=0.22->ipreent==0.1.0)
  Downloading winrt_windows_devices_enumeration-3.2.1-cp314-cp314-win_amd64.whl.metadata (1.5 kB)
Collecting winrt-windows-devices-radios>=3.1 (from bleak>=0.22->ipreent==0.1.0)
  Downloading winrt_windows_devices_radios-3.2.1-cp314-cp314-win_amd64.whl.metadata (1.1 kB)
Collecting winrt-windows-foundation>=3.1 (from bleak>=0.22->ipreent==0.1.0)
  Downloading winrt_windows_foundation-3.2.1-cp314-cp314-win_amd64.whl.metadata (1.0 kB)
Collecting winrt-windows-foundation-collections>=3.1 (from bleak>=0.22->ipreent==0.1.0)
  Downloading winrt_windows_foundation_collections-3.2.1-cp314-cp314-win_amd64.whl.metadata (1.1 kB)
Collecting winrt-windows-storage-streams>=3.1 (from bleak>=0.22->ipreent==0.1.0)
  Downloading winrt_windows_storage_streams-3.2.1-cp314-cp314-win_amd64.whl.metadata (1.3 kB)
Collecting typing_extensions>=4.12.2 (from winrt-runtime>=3.1->bleak>=0.22->ipreent==0.1.0)
  Downloading typing_extensions-4.16.0-py3-none-any.whl.metadata (3.3 kB)
Downloading bleak-3.0.2-py3-none-any.whl (146 kB)
Downloading pillow-12.3.0-cp314-cp314-win_amd64.whl (7.2 MB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 7.2/7.2 MB 30.2 MB/s  0:00:00
Downloading pypdfium2-5.14.0-py3-none-win_amd64.whl (3.9 MB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 3.9/3.9 MB 45.2 MB/s  0:00:00
Downloading pyserial-3.5-py2.py3-none-any.whl (90 kB)
Downloading winrt_runtime-3.2.1-cp314-cp314-win_amd64.whl (241 kB)
Downloading typing_extensions-4.16.0-py3-none-any.whl (45 kB)
Downloading winrt_windows_devices_bluetooth-3.2.1-cp314-cp314-win_amd64.whl (115 kB)
Downloading winrt_windows_devices_bluetooth_advertisement-3.2.1-cp314-cp314-win_amd64.whl (97 kB)
Downloading winrt_windows_devices_bluetooth_genericattributeprofile-3.2.1-cp314-cp314-win_amd64.whl (193 kB)
Downloading winrt_windows_devices_enumeration-3.2.1-cp314-cp314-win_amd64.whl (145 kB)
Downloading winrt_windows_devices_radios-3.2.1-cp314-cp314-win_amd64.whl (41 kB)
Downloading winrt_windows_foundation-3.2.1-cp314-cp314-win_amd64.whl (122 kB)
Downloading winrt_windows_foundation_collections-3.2.1-cp314-cp314-win_amd64.whl (70 kB)
Downloading winrt_windows_storage_streams-3.2.1-cp314-cp314-win_amd64.whl (135 kB)
Building wheels for collected packages: ipreent
  Building wheel for ipreent (pyproject.toml) ... done
  Created wheel for ipreent: filename=ipreent-0.1.0-py3-none-any.whl size=20275 sha256=2e30683c4938b246f9156a76d9e276cb638a661ee9ae48c3c6dc44db94974adc
  Stored in directory: C:\Users\mattia\AppData\Local\Temp\pip-ephem-wheel-cache-pbb00tm0\wheels\ca\88\2f\b4a4febfdbf106be7b2e9c6e911169ad890457da121df2abc6
Successfully built ipreent
Installing collected packages: pyserial, typing_extensions, pypdfium2, Pillow, winrt-runtime, winrt-windows-storage-streams, winrt-windows-foundation-collections, winrt-windows-foundation, winrt-windows-devices-radios, winrt-windows-devices-enumeration, winrt-windows-devices-bluetooth-genericattributeprofile, winrt-windows-devices-bluetooth-advertisement, winrt-windows-devices-bluetooth, bleak, ipreent
Successfully installed Pillow-12.3.0 bleak-3.0.2 ipreent-0.1.0 pypdfium2-5.14.0 pyserial-3.5 typing_extensions-4.16.0 winrt-runtime-3.2.1 winrt-windows-devices-bluetooth-3.2.1 winrt-windows-devices-bluetooth-advertisement-3.2.1 winrt-windows-devices-bluetooth-genericattributeprofile-3.2.1 winrt-windows-devices-enumeration-3.2.1 winrt-windows-devices-radios-3.2.1 winrt-windows-foundation-3.2.1 winrt-windows-foundation-collections-3.2.1 winrt-windows-storage-streams-3.2.1
(venv) PS C:\Users\mattia\Documents\Projects\ipreent> ipreent
usage: ipreent [-h] [-a ADDRESS] [-p PORT] [--rfcomm MAC] [--ble] [-m MODEL] [--width WIDTH] [--energy ENERGY]
               [--speed SPEED] [--rle | --no-rle]
               {scan,print,text,status,feed,preview,forget} ...
ipreent: error: the following arguments are required: cmd
(venv) PS C:\Users\mattia\Documents\Projects\ipreent> ipreent text "Prueba de iPreent"
Scanning for printers...
Error: No printer found. Is it on and not connected to the phone app?
(venv) PS C:\Users\mattia\Documents\Projects\ipreent> ipreent text "Prueba de iPreent"
Scanning for printers...
Found SC03h-5363 [63:53:D0:9A:FE:58]
SC03h prints over Bluetooth serial: RFCOMM to 63:53:D0:9A:FE:58
SC03h: 43 lines x1
  sending 100%
Printer: ready
(venv) PS C:\Users\mattia\Documents\Projects\ipreent> ipreent text "Prueba de iPreent" --ble
usage: ipreent [-h] [-a ADDRESS] [-p PORT] [--rfcomm MAC] [--ble]
               [-m MODEL] [--width WIDTH] [--energy ENERGY]
               [--speed SPEED] [--rle | --no-rle]
               {scan,print,text,status,feed,preview,forget} ...
ipreent: error: unrecognized arguments: --ble
(venv) PS C:\Users\mattia\Documents\Projects\ipreent> ipreent --ble text "Prueba de BLE"
Scanning for printers...
Found SC03h-5363 [63:53:D0:9A:FE:58]
SC03h: 43 lines x1
  sending 100%
Printer: ready
```