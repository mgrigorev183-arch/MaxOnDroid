"""Realistic adb output captured in the formats real devices print."""

DEVICES_EMPTY = "List of devices attached\n\n"

DEVICES_MIXED = """List of devices attached
R58M12ABCDE            device usb:1-4 product:beyond1lteeea model:SM_G973F device:beyond1 transport_id:3
192.168.1.40:5555      device product:aquaman model:MiTV_AFKR0 device:aquaman transport_id:5
adb-R58M12ABCDE-Xy12Ab._adb-tls-connect._tcp device product:beyond1lteeea model:SM_G973F device:beyond1 transport_id:6
ZY22BXYZ12             unauthorized usb:1-2 transport_id:7
emulator-5554          offline transport_id:1
0123ABCD               no permissions (user in plugdev group; are your udev rules wrong?); see [http://developer.android.com/tools/device.html] usb:1-3 transport_id:8

"""

MDNS_SERVICES = """List of discovered mdns services
adb-R58M12ABCDE-Xy12Ab\t_adb-tls-connect._tcp\t192.168.1.23:37159
maxondroid-AbCdEfGh\t_adb-tls-pairing._tcp.\t192.168.1.23:41231
adb-28041SKV0123\t_adb._tcp\t192.168.1.40:5555
broken line without address
"""

PHONE_PROPS = """[ro.product.model]: [SM-G973F]
[ro.product.manufacturer]: [samsung]
[ro.product.brand]: [samsung]
[ro.build.version.release]: [12]
[ro.build.version.sdk]: [31]
[ro.build.version.security_patch]: [2024-01-01]
[ro.build.characteristics]: [phone]
[ro.serialno]: [R58M12ABCDE]
[ro.product.cpu.abi]: [arm64-v8a]
[ro.build.display.id]: [SP1A.210812.016.G973FXXSGHWC2]
[persist.adb.tls_server.enable]: [1]
[service.adb.tls.port]: [37159]
[ro.multiline.example]: [first line
second line]
"""

TV_PROPS = """[ro.product.model]: [MiTV-AFKR0]
[ro.product.manufacturer]: [Xiaomi]
[ro.product.brand]: [Xiaomi]
[ro.build.version.release]: [12]
[ro.build.version.sdk]: [31]
[ro.build.version.security_patch]: [2023-09-01]
[ro.build.characteristics]: [tv]
[ro.serialno]: [28041SKV0123]
[service.adb.tcp.port]: [5555]
[persist.adb.tls_server.enable]: [0]
"""

PHONE_BATTERY = """Current Battery Service state:
  AC powered: false
  USB powered: true
  Wireless powered: false
  Max charging current: 500000
  status: 2
  health: 2
  present: true
  level: 87
  scale: 100
  voltage: 4215
  temperature: 296
  technology: Li-ion
"""

TV_BATTERY = """Current Battery Service state:
  AC powered: true
  USB powered: false
  Wireless powered: false
  status: 1
  health: 1
  present: false
  level: 0
  scale: 100
  temperature: 0
"""

DF_TOYBOX = """Filesystem     1K-blocks     Used Available Use% Mounted on
/dev/block/dm-5 115266384 28393856  86741424  25% /data
"""

DF_TOYBOX_WRAPPED = """Filesystem                1K-blocks    Used Available Use% Mounted on
/dev/block/bootdevice/by-name/userdata
                           25196544 9123456  16073088  37% /data
"""

DF_TOOLBOX = """Filesystem               Size     Used     Free   Blksize
/data                    25.1G     2.3G    22.7G   4096
"""

MEMINFO = """MemTotal:        7678772 kB
MemFree:          312340 kB
MemAvailable:    3456780 kB
Buffers:           12345 kB
"""

WM = """Physical size: 1080x2280
Override size: 1080x2400
Physical density: 420
"""

IP_PHONE = """1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000
    inet 127.0.0.1/8 scope host lo
       valid_lft forever preferred_lft forever
30: rmnet_data0: <UP,LOWER_UP> mtu 1500
    inet 10.55.12.7/30 scope global rmnet_data0
42: wlan0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state UP group default qlen 3000
    inet 192.168.1.23/24 brd 192.168.1.255 scope global wlan0
       valid_lft forever preferred_lft forever
"""

FEATURES_PHONE = """feature:android.hardware.telephony
feature:android.hardware.touchscreen
"""

FEATURES_TV = """feature:android.software.leanback
feature:android.hardware.type.television
"""


def info_output(props: str, battery: str, features: str, name: str = "null") -> str:
    return (
        "@@props\n" + props + "@@name\n" + name + "\n@@features\n" + features
        + "@@battery\n" + battery + "@@df\n" + DF_TOYBOX + "@@mem\n" + MEMINFO
        + "@@wm\n" + WM + "@@ip\n" + IP_PHONE + "@@end\n"
    )


def identity_output(props: str, features: str, name: str = "null") -> str:
    return "@@props\n" + props + "@@name\n" + name + "\n@@features\n" + features + "@@end\n"


PAIR_OK = "Successfully paired to 192.168.1.23:41231 [guid=adb-R58M12ABCDE-Xy12Ab]\n"
PAIR_BAD = "Failed: Wrong password or connection was dropped.\n"
CONNECT_OK = "connected to 192.168.1.23:37159\n"
CONNECT_ALREADY = "already connected to 192.168.1.40:5555\n"
CONNECT_REFUSED = "cannot connect to 192.168.1.99:5555: No connection could be made because the target machine actively refused it. (10061)\n"


# --- stage 2: packages ---------------------------------------------------------

PACKAGES_OUTPUT = """@@all
package:com.android.systemui
package:com.google.android.youtube.tv
package:com.google.android.tvrecommendations
package:com.google.android.apps.tv.launcherx
package:com.netflix.ninja
package:org.videolan.vlc
package:com.android.shell
package:com.google.android.inputmethod.latin
package:com.xiaomi.mitv.upgrade
package:not a package
@@installed
package:com.android.systemui
package:com.google.android.youtube.tv
package:com.google.android.apps.tv.launcherx
package:com.netflix.ninja
package:org.videolan.vlc
package:com.android.shell
package:com.google.android.inputmethod.latin
package:com.xiaomi.mitv.upgrade
@@system
package:com.android.systemui
package:com.google.android.youtube.tv
package:com.google.android.tvrecommendations
package:com.google.android.apps.tv.launcherx
package:com.netflix.ninja
package:com.android.shell
package:com.google.android.inputmethod.latin
package:com.xiaomi.mitv.upgrade
@@disabled
package:com.netflix.ninja
@@versions
  Package [com.android.systemui] (a1b2c3):
    versionCode=31 minSdk=31 targetSdk=31
    versionName=12
  Package [com.google.android.youtube.tv] (d4e5f6):
    versionCode=4012345 minSdk=21 targetSdk=33
    versionName=4.01.345
  Package [org.videolan.vlc] (778899):
    versionCode=13050407 minSdk=17 targetSdk=33
    versionName=3.5.4
@@home
priority=0 preferredOrder=0 match=0x108000 specificIndex=-1 isDefault=true
com.google.android.apps.tv.launcherx/.home.HomeActivity
@@ime
com.google.android.inputmethod.latin/com.android.inputmethod.latin.LatinIME
@@abi
arm64-v8a,armeabi-v7a,armeabi
arm64-v8a
@@sdk
31
@@density
Physical density: 320
@@leanback
true
@@end
"""

PM_PATH_SPLIT = """package:/data/app/~~abc==/org.videolan.vlc-xyz==/base.apk
package:/data/app/~~abc==/org.videolan.vlc-xyz==/split_config.arm64_v8a.apk
package:/data/app/~~abc==/org.videolan.vlc-xyz==/split_config.xhdpi.apk
"""
